"""Live wire contract, explicit recovery consent, and personal billing boundaries."""

import json
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
from conftest import ASGIClientFactory, PublicSettingsFactory
from pydantic import SecretStr
from test_personal_sessions import personal_runtime  # noqa: F401 - shared isolated fixture
from test_provider import MemorySocket
from voice_delegate.config import Settings
from voice_delegate.personal import PersonalSession, create_personal_session
from voice_delegate.providers.azure import AzureLiveProvider
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import Commentary, ProviderFailure
from voice_delegate.session.access import PersonalKeys
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import SessionError
from voice_delegate.session.preferences import VoicePreferences


async def test_azure_live_uses_live_urls_bearer_auth_and_client_delegation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_delegate.providers import openai

    socket = MemorySocket()
    requests: list[httpx.Request] = []
    attachments: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert str(request.url) == "https://test.openai.azure.com/openai/v1/live/sessions"
        assert request.headers["authorization"] == "Bearer personal-azure"
        payload = json.loads(request.content)
        assert payload["session"] == {
            "model": "my-live-deployment",
            "instructions": "trusted",
            "audio": {"output": {"voice": "marin"}},
            "delegation": {"type": "client"},
        }
        assert payload["transport"] == {"type": "webrtc", "sdp": "offer"}
        return httpx.Response(
            201, json={"session": {"id": "session1"}, "transport": {"sdp": "answer"}}
        )

    async def attach(url: str, **kwargs: Any) -> MemorySocket:
        attachments.append(url)
        assert kwargs["additional_headers"] == {"Authorization": "Bearer personal-azure"}
        return socket

    monkeypatch.setattr(openai, "connect", attach)
    provider = AzureLiveProvider(
        "https://test.openai.azure.com",
        "personal-azure",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    provider.model = "my-live-deployment"
    connection = await provider.connect(
        config=provider.default_config(
            "trusted", tuple(("user", "日本語" * 500) for _ in range(20))
        ),
        offer_sdp="offer",
    )
    assert connection.answer.sdp == "answer"
    assert attachments == ["wss://test.openai.azure.com/openai/v1/live/sessions/session1/attach"]
    replay = [json.loads(message) for message in socket.sent]
    assert len(replay) == 12
    assert all(
        event["type"] == "session.thinking.append" and event["delegation_id"] is None
        for event in replay
    )
    assert all(len(event["content"].encode()) <= 500 for event in replay)
    await connection.send(Commentary("task-1", "Result"))
    assert json.loads(socket.sent[-1])["type"] == "session.commentary.append"
    assert await connection.aclose()
    assert len(requests) == 1 and socket.closed
    await provider.aclose()


async def test_recovery_is_off_by_default_even_with_configured_fallback() -> None:
    primary, fallback = FakeProvider(), FakeProvider()
    manager = SessionManager(primary, Settings(), fallback=fallback)
    session = manager.create()
    await manager.connect(session, "offer")
    with pytest.raises(SessionError) as error:
        await manager.reconnect(session, "offer", 0)
    assert error.value.status == 501
    primary.connections[0].queue.put_nowait(ProviderFailure())
    assert session.watcher is not None
    await session.watcher
    assert session.state == "closed" and not fallback.connections
    await manager.aclose()


async def test_personal_recovery_never_borrows_platform_azure_keys() -> None:
    root = SessionManager(
        FakeProvider(),
        Settings(
            azure_endpoint="https://platform.openai.azure.com",
            azure_api_key=SecretStr("platform"),
        ),
    )
    with pytest.raises(SessionError) as error:
        await create_personal_session(
            root,
            PersonalSession(
                azure_recovery=True,
                keys=PersonalKeys(openai_key=SecretStr("mine")),
            ),
        )
    assert error.value.status == 422 and not root.sessions
    await root.aclose()


@pytest.mark.usefixtures("personal_runtime")
async def test_personal_recovery_and_debug_are_scoped_to_supplied_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from voice_delegate import personal

    captured: list[tuple[str, str, FakeProvider]] = []

    def azure(endpoint: str, key: str, *, close_timeout: float) -> FakeProvider:
        provider = FakeProvider()
        captured.append((endpoint, key, provider))
        return provider

    monkeypatch.setattr(personal, "AzureLiveProvider", azure)
    root = SessionManager(FakeProvider(), Settings(debug_directory=str(tmp_path)))
    session = await create_personal_session(
        root,
        PersonalSession(
            azure_recovery=True,
            debug_recording=True,
            keys=PersonalKeys(
                openai_key=SecretStr("mine"),
                azure_key=SecretStr("own-azure"),
                azure_endpoint="https://own.openai.azure.com",
                azure_deployment="own-live",
            ),
        ),
    )
    owner = root.owner_for(session)
    assert owner.settings.azure_deployment == "own-live" and owner.fallback is captured[0][2]
    assert captured[0][:2] == ("https://own.openai.azure.com", "own-azure")
    assert session.preferences.azure_recovery and session.debug is not None
    await root.close(session)
    for path in tmp_path.rglob("*.jsonl"):  # noqa: ASYNC240 - bounded test files
        assert "own-azure" not in path.read_text()
    assert not root.sessions
    await root.aclose()


def test_only_opted_in_recovery_reserves_a_second_voice_session(
    public_settings: PublicSettingsFactory,
    tmp_path: Path,
) -> None:
    for enabled in (False, True):
        settings = public_settings(tmp_path / str(enabled), daily_voice_seconds_global=100)
        manager = SessionManager(FakeProvider(), settings, fallback=FakeProvider())
        session = manager.create("alice", VoicePreferences(azure_recovery=enabled))
        database = manager.admission.database
        assert database is not None
        assert database.execute("SELECT seconds FROM reservations").fetchone() == (
            (22 if enabled else 11),
        )
        manager.admission.release(session.id)
        manager.admission.close()


@pytest.mark.parametrize("primary", ["openai", "azure"])
async def test_config_and_heartbeat_expose_recovery_consent(
    asgi_client: ASGIClientFactory,
    primary: Literal["openai", "azure"],
) -> None:
    from voice_delegate.api.app import create_app

    app = create_app(
        Settings(
            session_ui=True,
            voice_provider=primary,
            openai_api_key=SecretStr("fixture"),
            azure_endpoint="https://test.openai.azure.com",
            azure_api_key=SecretStr("fixture"),
        ),
        FakeProvider(),
    )
    async with asgi_client(app) as client:
        client.headers["Origin"] = "http://localhost:5173"
        assert (await client.post("/api/config")).json()["azure_recovery_available"]
        for enabled in (False, True):
            created = (
                await client.post(
                    "/api/sessions", json={"adapter": "openai", "azure_recovery": enabled}
                )
            ).json()
            client.headers["X-Session-Key"] = created["key"]
            path = "/api/sessions/" + created["id"]
            status = (await client.post(path + "/heartbeat")).json()
            assert status["fallback_available"] is enabled
            await client.post(path + "/close")


@pytest.mark.parametrize(
    "target",
    [
        "http://public.example",
        "http://8.8.8.8",
        "http://169.254.169.254",
        "http://unrecognized-service",
        "http://worker.example",
    ],
)
def test_personal_worker_refuses_plaintext_public_destinations(target: str) -> None:
    from voice_delegate.scaling.remote import RemoteWorker

    settings = Settings(worker_service_url=target)
    with pytest.raises(ValueError, match="private transport or HTTPS"):
        RemoteWorker(settings, personal_keys=PersonalKeys(openai_key=SecretStr("mine")))


@pytest.mark.parametrize(
    "target",
    [
        "https://worker.example",
        "http://worker:8001",
        "http://127.0.0.1:8001",
        "http://10.0.0.2:8001",
        "http://172.20.0.2",
        "http://192.168.1.2",
        "http://[fd00::2]",
    ],
)
def test_private_worker_transport_policy_preserves_documented_topologies(target: str) -> None:
    from voice_delegate.config import worker_transport_allowed

    assert worker_transport_allowed(target)


def test_lease_schema_upgrade_preserves_existing_sessions(
    public_settings: PublicSettingsFactory,
    tmp_path: Path,
) -> None:
    import sqlite3

    from voice_delegate.admission.policy import Admission

    settings = public_settings(tmp_path)
    database = sqlite3.connect(settings.quota_database)
    database.execute(
        "CREATE TABLE leases (session_id TEXT PRIMARY KEY, principal TEXT, expires REAL)"
    )
    database.execute("INSERT INTO leases VALUES ('old-session', 'old-principal', 9999999999)")
    database.commit()
    database.close()
    admission = Admission(settings)
    assert admission.database is not None
    assert admission.database.execute("SELECT session_id, personal FROM leases").fetchone() == (
        "old-session",
        0,
    )
    admission.close()
