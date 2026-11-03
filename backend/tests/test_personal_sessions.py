"""Personal keys are scoped to one owned session and never borrow platform credentials."""

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import ASGIClientFactory, PublicSettingsFactory
from pydantic import SecretStr
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings, load_settings
from voice_delegate.delegation.planner import PlannerRuntime
from voice_delegate.personal import PersonalSession, create_personal_session
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.scaling.remote import RemoteWorker
from voice_delegate.scaling.worker_service import JobInput, Jobs
from voice_delegate.session.access import PersonalKeys
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import SessionError
from voice_delegate_agent.graph import OfflinePlanner


@pytest.fixture
def personal_runtime(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from voice_delegate import personal

    captured: dict[str, Any] = {"voices": [], "workers": []}

    def voice(key: str, _timeout: float) -> FakeProvider:
        provider = FakeProvider()
        captured["voices"].append((key, provider))
        return provider

    def planner(settings: Settings) -> PlannerRuntime:
        captured["workers"].append(settings)
        return PlannerRuntime(OfflinePlanner())

    monkeypatch.setattr(personal, "OpenAILiveProvider", voice)
    monkeypatch.setattr(personal, "build_planner", planner)
    return captured


async def test_personal_session_isolated_and_released(personal_runtime: dict[str, Any]) -> None:
    root = SessionManager(
        FakeProvider(),
        Settings(
            openai_api_key=SecretStr("platform-key"), tavily_api_key=SecretStr("platform-search")
        ),
    )
    body = PersonalSession(adapter="openai", keys=PersonalKeys(openai_key=SecretStr("my-key")))
    session = await create_personal_session(root, body)
    owner = root.owner_for(session)
    assert owner is not root
    assert personal_runtime["voices"][0][0] == "my-key"
    assert personal_runtime["workers"][0].openai_api_key.get_secret_value() == "my-key"
    assert not personal_runtime["workers"][0].tavily_api_key.get_secret_value()
    assert not owner.settings.fallback_enabled and owner.fallback is None
    assert owner.settings.debug_recording and session.debug is None
    with pytest.raises(SessionError):
        await create_personal_session(root, body)
    await owner.connect(session, "v=0\r\n")
    await root.close(session)
    assert session.owner is None and session.release_personal is None
    assert not root.sessions
    assert personal_runtime["voices"][0][1].connections[0].closed
    await root.aclose()


async def test_personal_without_invitation_platform_still_gated(
    asgi_client: ASGIClientFactory, personal_runtime: dict[str, Any]
) -> None:
    app = create_app(Settings(access_token=SecretStr("platform-invitation")), FakeProvider())
    async with asgi_client(app) as client:
        client.headers["Origin"] = "http://localhost:5173"
        assert (await client.post("/api/sessions", json={})).status_code == 401
        created = await client.post(
            "/api/personal/sessions",
            json={"adapter": "openai", "keys": {"openai_key": "my-private-key"}},
        )
        assert created.status_code == 201
        assert "my-private-key" not in created.text
        data = created.json()
        path = f"/api/sessions/{data['id']}"
        assert (await client.post(path + "/heartbeat")).status_code == 404
        client.headers["X-Session-Key"] = data["key"]
        assert (await client.post(path + "/heartbeat")).status_code == 200
        assert (await client.post(path + "/close")).status_code == 200
    assert personal_runtime["voices"][0][0] == "my-private-key"


@pytest.mark.parametrize(
    "body",
    [
        {"adapter": "openai", "keys": {"openai_key": {"secret": "do-not-echo"}}},
        {"adapter": "openai", "keys": {"openai_key": "do-not-echo", "unknown": "do-not-echo"}},
        {
            "adapter": "azure",
            "keys": {"azure_key": "do-not-echo", "azure_endpoint": "http://localhost"},
        },
        {"adapter": "openai", "keys": {}},
    ],
)
async def test_invalid_personal_inputs_never_echo_keys(
    asgi_client: ASGIClientFactory, body: dict[str, object]
) -> None:
    app = create_app(Settings(), FakeProvider())
    async with asgi_client(app) as client:
        client.headers["Origin"] = "http://localhost:5173"
        result = await client.post("/api/personal/sessions", json=body)
        assert result.status_code == 422
        assert "do-not-echo" not in result.text


async def test_personal_expiry_releases_clients(personal_runtime: dict[str, Any]) -> None:
    now = [0.0]
    root = SessionManager(FakeProvider(), Settings(session_ttl_seconds=1), clock=lambda: now[0])
    session = await create_personal_session(
        root, PersonalSession(keys=PersonalKeys(openai_key=SecretStr("expires")))
    )
    now[0] = 2
    await root.expire()
    assert not root.sessions and session.owner is None
    await root.aclose()


async def test_remote_personal_worker_receives_only_worker_keys() -> None:
    posts: list[dict[str, Any]] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        import json

        if request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(202, json={"personal": True})
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"status": "completed", "text": "4", "usage": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        worker = RemoteWorker(
            Settings(openai_api_key=SecretStr("platform")),
            http,
            personal_keys=PersonalKeys(
                openai_key=SecretStr("mine"),
                tavily_key=SecretStr("search-mine"),
                elevenlabs_key=SecretStr("voice-only"),
            ),
        )
        assert (await worker.delegate_task("calculate 2+2", "")).text == "4"
        assert posts[0]["personal_keys"] == {"openai_key": "mine", "tavily_key": "search-mine"}
        assert "platform" not in str(posts) and "voice-only" not in str(posts)
        await worker.aclose()
        assert worker.personal_keys is None


async def test_remote_job_discards_personal_keys_and_closes_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time
    from uuid import uuid4

    from voice_delegate.scaling import worker_service

    runtime = PlannerRuntime(OfflinePlanner())
    captured: list[Settings] = []

    def planner(settings: Settings) -> PlannerRuntime:
        captured.append(settings)
        return runtime

    monkeypatch.setattr(worker_service, "build_planner", planner)
    jobs = Jobs(runtime.worker(4), Settings(openai_api_key=SecretStr("platform")))
    body = JobInput(
        request_id=uuid4(),
        goal="calculate 2+2",
        deadline=time.time() + 30,
        personal_keys=PersonalKeys(openai_key=SecretStr("mine")),
    )
    job = jobs.start(body)
    assert job.task is not None
    await job.task
    assert job.status == "completed" and body.personal_keys is None
    assert captured[0].openai_api_key.get_secret_value() == "mine"
    assert not captured[0].tavily_api_key.get_secret_value()
    await jobs.aclose()


def test_runtime_flags_are_automatic_and_old_flags_do_not_disable_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(str(tmp_path))
    for name in [
        "VOICE_COST_ESTIMATES",
        "VOICE_SESSION_UI",
        "VOICE_INTENT_CANCELLATION",
        "VOICE_AUDIO_TIMING",
        "VOICE_NATIVE_CLIENTS",
        "VOICE_DEBUG_RECORDING",
        "VOICE_OTEL_ENABLED",
    ]:
        monkeypatch.setenv(name, "false")
    settings = load_settings()
    assert settings.cost_estimates and settings.session_ui and settings.intent_cancellation
    assert settings.audio_timing and settings.native_clients
    assert settings.debug_recording and settings.otel_enabled


async def test_personal_close_failure_still_discards_the_session(
    personal_runtime: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = SessionManager(FakeProvider(), Settings())
    session = await create_personal_session(
        root, PersonalSession(keys=PersonalKeys(openai_key=SecretStr("mine")))
    )
    owner = root.owner_for(session)
    await owner.connect(session, "v=0\r\n")
    assert session.connection is not None

    async def fail() -> bool:
        raise RuntimeError("transport close failed")

    monkeypatch.setattr(session.connection, "aclose", fail)
    with pytest.raises(RuntimeError, match="transport close failed"):
        await root.close(session)
    assert not root.sessions
    assert session.owner is None and session.release_personal is None
    await root.aclose()


async def test_old_remote_worker_never_gets_a_platform_job() -> None:
    paths: list[tuple[str, str]] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        return httpx.Response(404, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        worker = RemoteWorker(
            Settings(), http, personal_keys=PersonalKeys(openai_key=SecretStr("mine"))
        )
        with pytest.raises(httpx.HTTPStatusError):
            await worker.delegate_task("calculate 2+2", "")
        assert paths[0] == ("POST", "/personal-jobs")
        assert ("POST", "/jobs") not in paths
        await worker.aclose()


async def test_personal_elevenlabs_bootstrap_uses_owned_agent_and_token(
    asgi_client: ASGIClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_delegate.providers.elevenlabs import BrowserBootstrap, ElevenLabsProvider

    checked: list[tuple[str, str]] = []

    async def validate(self: ElevenLabsProvider, _ttl: float) -> None:
        checked.append((self.agent_id, self._api_key))

    async def prepare(self: ElevenLabsProvider) -> BrowserBootstrap:
        return BrowserBootstrap(conversation_id="conv_personal", token="ephemeral")

    async def confirm(self: ElevenLabsProvider, _conversation: str, _usage: object = None) -> bool:
        return True

    monkeypatch.setattr(ElevenLabsProvider, "validate_agent", validate)
    monkeypatch.setattr(ElevenLabsProvider, "prepare_browser", prepare)
    monkeypatch.setattr(ElevenLabsProvider, "confirm_closed", confirm)
    settings = Settings(
        elevenlabs_webhook_token=SecretStr("q" * 32),
        elevenlabs_webhook_url="https://backend.example/integrations/elevenlabs/delegate",
    )
    app = create_app(settings, FakeProvider())
    async with asgi_client(app) as client:
        client.headers["Origin"] = "http://localhost:5173"
        created = await client.post(
            "/api/personal/sessions",
            json={
                "adapter": "elevenlabs",
                "keys": {
                    "elevenlabs_key": "personal-eleven",
                    "elevenlabs_agent_id": "agent_personal",
                    "elevenlabs_webhook_token": "p" * 32,
                },
            },
        )
        assert created.status_code == 201
        session = created.json()
        path = f"/api/sessions/{session['id']}"
        client.headers["X-Session-Key"] = session["key"]
        bootstrap = await client.post(path + "/elevenlabs/bootstrap")
        assert bootstrap.status_code == 200
        assert checked == [("agent_personal", "personal-eleven")]
        assert "personal-eleven" not in bootstrap.text
        assert "p" * 32 not in bootstrap.text
        # A different session/platform service token cannot authenticate this conversation.
        denied = await client.post(
            "/integrations/elevenlabs/delegate",
            headers={"X-Voice-Webhook-Token": "q" * 32, "X-Voice-Conversation-Id": "conv_personal"},
            json={"goal": "calculate 2+2"},
        )
        assert denied.status_code == 401
        await client.post(
            path + "/elevenlabs/events",
            json={"kind": "connected", "sequence": 0, "conversation_id": "conv_personal"},
        )
        await client.post(path + "/elevenlabs/events", json={"kind": "activity", "sequence": 1})
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as service:
            result = await asyncio.wait_for(
                service.post(
                    "/integrations/elevenlabs/delegate",
                    headers={
                        "X-Voice-Webhook-Token": "p" * 32,
                        "X-Voice-Conversation-Id": "conv_personal",
                    },
                    json={"goal": "calculate 2+2"},
                ),
                timeout=3,
            )
            assert result.status_code == 200
            assert "4" in result.json()["result"]
        assert (await client.post(path + "/close")).status_code == 200


async def test_personal_leases_share_capacity_without_spending_platform_daily_allowance(
    public_settings: PublicSettingsFactory,
    tmp_path: Path,
    personal_runtime: dict[str, Any],
) -> None:
    settings = public_settings(tmp_path, max_sessions=2)
    first = SessionManager(FakeProvider(), settings)
    second = SessionManager(FakeProvider(), settings)
    session = await create_personal_session(
        first, PersonalSession(keys=PersonalKeys(openai_key=SecretStr("private-personal-key")))
    )
    db = first.admission.database
    assert db is not None
    assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 1
    assert "private-personal-key" not in str(db.execute("SELECT * FROM leases").fetchall())
    with pytest.raises(SessionError) as busy:
        await create_personal_session(
            second, PersonalSession(keys=PersonalKeys(openai_key=SecretStr("another-personal-key")))
        )
    assert busy.value.status == 429
    platform = second.create("alice")
    await first.close(session)
    assert platform.principal == "alice"
    assert db.execute("SELECT SUM(sessions) FROM reservations").fetchone()[0] == 1
    await first.aclose()
    await second.aclose()


async def test_credential_presence_enables_platform_providers_despite_old_off_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    asgi_client: ASGIClientFactory,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("VOICE_ELEVENLABS_ENABLED", "VOICE_WEB_SEARCH", "VOICE_FALLBACK_ENABLED"):
        monkeypatch.setenv(name, "false")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fixture-eleven")
    monkeypatch.setenv("VOICE_ELEVENLABS_AGENT_ID", "agent_fixture")
    monkeypatch.setenv("VOICE_ELEVENLABS_WEBHOOK_TOKEN", "w" * 32)
    monkeypatch.setenv(
        "VOICE_ELEVENLABS_WEBHOOK_URL", "https://backend.example/integrations/elevenlabs/delegate"
    )
    monkeypatch.setenv("TAVILY_API_KEY", "fixture-search")
    monkeypatch.setenv("VOICE_AZURE_API_KEY", "fixture-azure")
    monkeypatch.setenv("VOICE_AZURE_ENDPOINT", "https://resource.openai.azure.com")
    settings = load_settings()
    assert settings.elevenlabs_enabled and settings.web_search and settings.fallback_enabled
    app = create_app(settings, FakeProvider())
    async with asgi_client(app) as client:
        client.headers["Origin"] = "http://localhost:5173"
        config = (await client.post("/api/config")).json()
        assert "elevenlabs" in config["available_adapters"]
        assert "azure" in config["available_adapters"]


async def test_personal_elevenlabs_rejects_short_webhook_token() -> None:
    root = SessionManager(FakeProvider(), Settings())
    body = PersonalSession(
        adapter="elevenlabs",
        keys=PersonalKeys(
            elevenlabs_key=SecretStr("el-key"),
            elevenlabs_agent_id="agent_abc123",
            elevenlabs_webhook_token=SecretStr("too-short"),
        ),
    )
    with pytest.raises(SessionError) as error:
        await create_personal_session(root, body)
    assert error.value.status == 422
    assert "at least 32" in str(error.value)
    assert not root.sessions


def test_plaintext_worker_transport_allows_railway_private_hosts_only() -> None:
    from voice_delegate.config import worker_transport_allowed

    assert worker_transport_allowed("http://worker.railway.internal:8001")
    assert not worker_transport_allowed("http://worker.railway.internal.example.com")
    assert not worker_transport_allowed("http://railway.internal")
    assert not worker_transport_allowed("http://example.com:8001")
    assert worker_transport_allowed("https://example.com")


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "foo.openai.azure.com",
        "http://foo.openai.azure.com",
        "https://foo.openai.azure.com/openai/v1",
        "https://foo.cognitiveservices.azure.com",
        "https://foo.openai.azure.com:8443",
    ],
)
async def test_personal_azure_explains_a_rejected_resource_origin(endpoint: str) -> None:
    root = SessionManager(FakeProvider(), Settings())
    body = PersonalSession(
        adapter="azure",
        keys=PersonalKeys(azure_key=SecretStr("azure-key"), azure_endpoint=endpoint),
    )
    with pytest.raises(SessionError) as error:
        await create_personal_session(root, body)
    assert error.value.status == 422
    assert "https://<resource>.openai.azure.com" in str(error.value)
    assert "azure-key" not in str(error.value)
    assert not root.sessions


def test_azure_origin_accepts_resource_origin_with_optional_slash() -> None:
    from voice_delegate.config import azure_origin_allowed

    assert azure_origin_allowed("https://foo.openai.azure.com")
    assert azure_origin_allowed("https://foo.openai.azure.com/")
    assert azure_origin_allowed("https://foo.openai.azure.com:443")
