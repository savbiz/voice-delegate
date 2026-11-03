"""Opt-in Agents bootstrap and webhook configuration contracts, never live."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from conftest import ASGIClientFactory
from pydantic import SecretStr, ValidationError
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.providers.elevenlabs import MAX_RESPONSE_BYTES, ElevenLabsProvider
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import ProviderError, ProviderUsage, UnsupportedCapability


async def test_typed_bootstrap_uses_fixed_endpoint_and_no_sdp() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json={"token": "ephemeral-fixture", "conversation_id": "conv_fixture"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        provider = ElevenLabsProvider("server-fixture", "agent_fixture", http=http)
        result = await provider.prepare_browser()
        assert result.transport == "elevenlabs_agents_webrtc"
        assert result.conversation_id == "conv_fixture"
        assert result.token == "ephemeral-fixture"
        assert "ephemeral-fixture" not in repr(result)
        assert len(requests) == 1
        assert requests[0].url.host == "api.elevenlabs.io"
        assert requests[0].url.path == "/v1/convai/conversation/token"
        assert requests[0].url.params["agent_id"] == "agent_fixture"
        assert requests[0].headers["xi-api-key"] == "server-fixture"
        config = provider.default_config("trusted")
        with pytest.raises(UnsupportedCapability):
            await provider.connect(config=config, offer_sdp="v=0\r\n")
        with pytest.raises(UnsupportedCapability):
            await provider.issue_client_credential(config)
        assert not provider.capabilities.server_control
        await provider.aclose()
        assert http.is_closed


@pytest.mark.parametrize("failure", ["status", "redirect", "json", "shape", "oversize", "network"])
async def test_bootstrap_failure_is_bounded_redacted_and_never_retried(failure: str) -> None:
    requests = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if failure == "network":
            raise httpx.ConnectError("private provider response", request=request)
        if failure == "oversize":
            return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
        if failure == "status":
            return httpx.Response(401, text="private provider response")
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://other.example/"})
        return httpx.Response(
            200, content=b"no-json" if failure == "json" else json.dumps({"token": ""}).encode()
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(ProviderError, match=r"^ElevenLabs session setup unavailable$"):
            await ElevenLabsProvider("test", "agent_fixture", http=http).prepare_browser()
    assert requests == 1


async def test_timeout_does_not_swallow_task_cancellation() -> None:
    waiting = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        waiting.set()
        await asyncio.Event().wait()
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(ProviderError):
            await ElevenLabsProvider(
                "test", "agent_fixture", timeout=0.01, http=http
            ).prepare_browser()
        waiting.clear()
        task = asyncio.create_task(
            ElevenLabsProvider("test", "agent_fixture", http=http).prepare_browser()
        )
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_preview_requires_credentials_and_explicit_selection() -> None:
    assert not Settings().elevenlabs_enabled
    with pytest.raises(ValidationError, match="requires ELEVENLABS_API_KEY"):
        Settings(elevenlabs_enabled=True)
    with pytest.raises(ValidationError, match="VOICE_ELEVENLABS_ENABLED"):
        Settings(voice_provider="elevenlabs")


@pytest.mark.parametrize("connected", [False, True])
async def test_bootstrap_route_is_owned_one_shot_and_blocks_sdp_setup(
    asgi_client: ASGIClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    connected: bool,
) -> None:
    settings = Settings(
        voice_provider="elevenlabs",
        intent_cancellation=True,
        elevenlabs_enabled=True,
        elevenlabs_webhook_token=SecretStr("w" * 32),
        elevenlabs_webhook_url="https://backend.example/integrations/elevenlabs/delegate",
        elevenlabs_api_key=SecretStr("server-fixture"),
        elevenlabs_agent_id="agent_fixture",
    )
    calls = 0

    async def prepare(self: ElevenLabsProvider) -> object:
        from voice_delegate.providers.elevenlabs import BrowserBootstrap

        nonlocal calls
        calls += 1
        return BrowserBootstrap("conv_fixture", "ephemeral-fixture")

    async def validate(self: ElevenLabsProvider, ttl: float) -> None:
        pass

    async def confirm(
        self: ElevenLabsProvider,
        conversation_id: str,
        on_usage: Callable[[ProviderUsage], None] | None = None,
    ) -> bool:
        assert conversation_id == "conv_fixture"
        assert on_usage is not None
        on_usage(ProviderUsage(credits=123, voice_surcharge_credits=2, usd=0.01))
        return True

    monkeypatch.setattr(ElevenLabsProvider, "confirm_closed", confirm)
    monkeypatch.setattr(ElevenLabsProvider, "validate_agent", validate)
    monkeypatch.setattr(ElevenLabsProvider, "prepare_browser", prepare)
    app = create_app(settings)
    async with asgi_client(app) as client:
        client.headers["Origin"] = "http://localhost:5173"
        session = (await client.post("/api/sessions")).json()
        path = f"/api/sessions/{session['id']}/elevenlabs/bootstrap"
        assert (await client.post(path)).status_code == 404
        client.headers["X-Session-Key"] = session["key"]
        response = await client.post(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["token"] == "ephemeral-fixture"
        assert "sdp" not in response.json()
        assert (await client.post(path)).status_code == 409
        assert (
            await client.post(f"/api/sessions/{session['id']}/offer", json={"sdp": "v=0\r\n"})
        ).status_code == 409
        assert calls == 1
        if connected:
            assert (
                await client.post(
                    f"/api/sessions/{session['id']}/elevenlabs/events",
                    json={"kind": "connected", "sequence": 0, "conversation_id": "conv_fixture"},
                )
            ).status_code == 200
        closed = (await client.post(f"/api/sessions/{session['id']}/close")).json()
        assert closed["finalized"] is connected
        receipt = closed["costs"]["provider_usage"]
        if connected:
            assert receipt["credits"] == 123
            assert receipt["voice_surcharge_credits"] == 2
        else:
            assert receipt is None


async def test_default_app_does_not_enable_elevenlabs(asgi_client: ASGIClientFactory) -> None:
    async with asgi_client(create_app(Settings(), FakeProvider())) as client:
        client.headers["Origin"] = "http://localhost:5173"
        session = (await client.post("/api/sessions")).json()
        client.headers["X-Session-Key"] = session["key"]
        response = await client.post(f"/api/sessions/{session['id']}/elevenlabs/bootstrap")
        assert response.status_code == 501


async def test_failed_bootstrap_consumes_attempt_and_redacts_upstream_failure(
    asgi_client: ASGIClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        voice_provider="elevenlabs",
        intent_cancellation=True,
        elevenlabs_enabled=True,
        elevenlabs_webhook_token=SecretStr("w" * 32),
        elevenlabs_webhook_url="https://backend.example/integrations/elevenlabs/delegate",
        elevenlabs_api_key=SecretStr("server-fixture"),
        elevenlabs_agent_id="agent_fixture",
    )
    calls = 0

    async def prepare(self: ElevenLabsProvider) -> object:
        nonlocal calls
        calls += 1
        message = "ElevenLabs session setup unavailable"
        raise ProviderError(message)

    async def validate(self: ElevenLabsProvider, ttl: float) -> None:
        pass

    monkeypatch.setattr(ElevenLabsProvider, "validate_agent", validate)
    monkeypatch.setattr(ElevenLabsProvider, "prepare_browser", prepare)
    async with asgi_client(create_app(settings)) as client:
        client.headers["Origin"] = "http://localhost:5173"
        session = (await client.post("/api/sessions")).json()
        client.headers["X-Session-Key"] = session["key"]
        url = f"/api/sessions/{session['id']}/elevenlabs/bootstrap"
        response = await client.post(url)
        assert response.status_code == 502
        assert response.json()["detail"] == "ElevenLabs session setup unavailable"
        assert "server-fixture" not in response.text
        assert (await client.post(url)).status_code == 409
        assert calls == 1


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "public",
        "sync",
        "extra_tool",
        "duration",
        "overrides",
        "client",
        "url",
        "auth",
        "binding",
        "method",
        "extra_param",
        "builtin",
        "duplicate_header",
        "optional_goal",
        "static_goal",
        "dynamic_goal",
        "mtls",
        "workflow_edge",
        "workflow_prompt",
        "workflow_subgraph",
        "duplicate_tool_id",
    ],
)
@pytest.mark.parametrize("dashboard", [False, True])
@pytest.mark.parametrize("catalog", ["inline", "referenced", "expanded"])
async def test_agent_policy_is_validated_before_credentials(
    change: str, dashboard: bool, catalog: str
) -> None:
    tool: dict[str, Any] = {
        "type": "webhook",
        "name": "delegate_task",
        "execution_mode": "async",
        "response_timeout_secs": 120,
        "api_schema": {
            "url": "https://backend.example/integrations/elevenlabs/delegate",
            "method": "POST",
            "request_headers": {
                "X-Voice-Webhook-Token": {"secret_id": "fixture-stored-token"},
                "X-Voice-Conversation-Id": {"variable_name": "system__conversation_id"},
            },
            "request_body_schema": {
                "type": "object",
                "required": ["goal"],
                "properties": {"goal": {"type": "string", "description": "Task"}},
            },
        },
    }
    agent: dict[str, Any] = {
        "platform_settings": {
            "auth": {"enable_auth": change != "public"},
            "overrides": {"prompt": change == "overrides"},
        },
        "conversation_config": {
            "conversation": {"max_duration_seconds": 301 if change == "duration" else 300},
            "agent": {"prompt": {"tools": [tool, tool] if change == "extra_tool" else [tool]}},
        },
    }
    if change == "sync":
        tool["execution_mode"] = "immediate"
    if change == "client":
        tool["type"] = "client"
    if change == "url":
        tool["api_schema"]["url"] = "https://untrusted.example/"
    if change == "auth":
        tool["api_schema"]["request_headers"]["X-Voice-Webhook-Token"] = "plain-text"
    if change == "binding":
        tool["api_schema"]["request_headers"]["X-Voice-Conversation-Id"] = "model supplied"
    if change == "method":
        tool["api_schema"]["method"] = "GET"
    if change == "extra_param":
        tool["api_schema"]["request_body_schema"]["properties"]["owner"] = {"type": "string"}
    if change == "builtin":
        agent["conversation_config"]["agent"]["prompt"]["built_in_tools"] = {"other": {}}

    if dashboard:
        schema = tool["api_schema"]
        schema["request_headers"] = [
            {
                "type": "secret" if name == "X-Voice-Webhook-Token" else "dynamic_variable",
                "name": name,
                **(value if isinstance(value, dict) else {"value": value}),
            }
            for name, value in schema["request_headers"].items()
        ]
        body = schema["request_body_schema"]
        body["properties"] = [
            {
                "id": name,
                "required": name in body["required"],
                "value_type": "llm_prompt",
                "dynamic_variable": "",
                "constant_value": "",
                "is_system_provided": False,
                **value,
            }
            for name, value in body["properties"].items()
        ]
        body["required"] = False
        body["value_type"] = "llm_prompt"

    schema = tool["api_schema"]
    if change == "duplicate_header":
        if dashboard:
            header = dict(schema["request_headers"][0])
            header["name"] = header["name"].lower()
            schema["request_headers"].append(header)
        else:
            schema["request_headers"]["x-voice-webhook-token"] = {"secret_id": "other"}
    if change == "optional_goal":
        if dashboard:
            schema["request_body_schema"]["properties"][0]["required"] = False
        else:
            schema["request_body_schema"]["required"] = []
    if change in {"static_goal", "dynamic_goal"}:
        properties = schema["request_body_schema"]["properties"]
        goal = properties[0] if dashboard else properties["goal"]
        goal["value_type"] = "constant" if change == "static_goal" else "dynamic_variable"
    if change == "mtls":
        schema["mtls_auth_connection"] = {"id": "unexpected"}

    prompt = agent["conversation_config"]["agent"]["prompt"]
    if catalog != "inline":
        agent["workflow"] = {
            "nodes": {
                "start_node": {
                    "type": "start",
                    "position": {"x": 0, "y": 0},
                    "edge_order": [],
                    "parent_subgraph_id": None,
                }
            },
            "edges": {},
            "subgraphs": {},
            "prevent_subagent_loops": False,
        }
        prompt.setdefault("built_in_tools", {"end_call": None, "language_detection": None})
        prompt["tool_ids"] = ["tool_fixture"]
        if catalog == "referenced" and change != "extra_tool":
            prompt["tools"] = []
    if change.startswith("workflow_"):
        workflow = agent.setdefault(
            "workflow",
            {"nodes": {"start_node": {"type": "start"}}, "edges": {}, "subgraphs": {}},
        )
        if change == "workflow_edge":
            workflow["edges"] = {"edge": {"source": "start_node", "target": "other"}}
        if change == "workflow_prompt":
            workflow["nodes"]["start_node"]["additional_prompt"] = "Unexpected override"
        if change == "workflow_subgraph":
            workflow["subgraphs"] = {"extra": {}}
    if change == "duplicate_tool_id":
        prompt["tool_ids"] = ["tool_fixture", "tool_fixture"]

    def respond(request: httpx.Request) -> httpx.Response:
        resolved = json.loads(json.dumps(tool))
        if change == "conflicting_reference":
            if dashboard:
                resolved["api_schema"]["request_headers"][0]["secret_id"] = "other-stored-token"
            else:
                resolved["api_schema"]["request_headers"]["X-Voice-Webhook-Token"] = {
                    "secret_id": "other-stored-token"
                }
        payload = {"tool_config": resolved} if "/tools/" in request.url.path else agent
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        provider = ElevenLabsProvider(
            "fixture",
            "agent_fixture",
            http=http,
            webhook_url="https://backend.example/integrations/elevenlabs/delegate",
        )
        if change == "none":
            await provider.validate_agent(300)
        else:
            with pytest.raises(ProviderError, match="private async"):
                await provider.validate_agent(300)


@pytest.mark.parametrize("dashboard", [False, True])
async def test_expanded_and_referenced_tool_must_agree(dashboard: bool) -> None:
    await test_agent_policy_is_validated_before_credentials(
        "conflicting_reference", dashboard, "expanded"
    )


async def test_sdk_connection_deduplication_bounds_and_verified_close() -> None:
    from voice_delegate.providers.elevenlabs_session import ElevenLabsConnection
    from voice_delegate.providers.models import Commentary

    async def confirm() -> bool:
        return True

    connection = ElevenLabsConnection("conv_fixture", confirm)
    connection.start()
    connection.delegate("native-one", "calculate 2+2")
    connection.delegate("native-one", "calculate 2+2")
    assert len(connection.calls) == 1
    with pytest.raises(ProviderError, match="reused"):
        connection.delegate("native-one", "different")
    await connection.send(Commentary("native-one", "4"))
    assert connection.calls["native-one"].result == "4"
    with pytest.raises(ProviderError):
        await connection.send(Commentary("missing", "4"))
    with pytest.raises(ProviderError):
        await connection.send(Commentary("native-one", "é" * 251))
    assert await connection.aclose()
    assert not await connection.aclose()


async def test_sdk_speech_preserves_work_and_explicit_cancel_settles_native_call(
    blocking_worker: object,
    fake_clock: object,
) -> None:
    from conftest import BlockingWorker, FakeClock
    from voice_delegate.providers.elevenlabs_session import ElevenLabsConnection
    from voice_delegate.providers.models import SpeechStarted
    from voice_delegate.session.manager import SessionManager

    assert isinstance(blocking_worker, BlockingWorker)
    assert isinstance(fake_clock, FakeClock)

    async def confirm() -> bool:
        return False

    manager = SessionManager(
        FakeProvider(), Settings(intent_cancellation=True), worker=blocking_worker, clock=fake_clock
    )
    session = manager.create()
    connection = ElevenLabsConnection("conv_fixture", confirm)
    manager.attach_sdk(session, connection)
    connection.start()
    try:
        connection.delegate("first", "calculate 2+2")
        await blocking_worker.started.wait()
        connection.emit(SpeechStarted())
        connection.delegate("second", "calculate 3+4")
        for _ in range(100):
            if "second" in session.portfolio.jobs:
                break
            await asyncio.sleep(0)
        assert session.portfolio.jobs["first"].status == "running"
        assert session.portfolio.jobs["second"].status == "running"
        manager.interrupt(session, task_id="second")
        assert session.portfolio.jobs["first"].status == "running"
        assert session.portfolio.jobs["second"].status == "cancelled"
        await manager.intent.deliver(session.portfolio, connection, 0)
        assert "cancelled" in (connection.calls["second"].result or "")
    finally:
        await manager.aclose()


@pytest.mark.parametrize(
    ("change", "confirmed", "receipt"),
    [
        ("none", True, True),
        ("zero", True, True),
        ("pending", False, False),
        ("foreign_agent", False, False),
        ("foreign_conversation", False, False),
        ("missing", True, False),
        ("negative", True, False),
        ("boolean", True, False),
        ("invalid_usd", True, False),
        ("failure", False, False),
    ],
)
async def test_close_reports_only_bounded_owned_provider_charges(
    change: str, confirmed: bool, receipt: bool
) -> None:
    metadata: dict[str, Any] = {
        "cost": 296,
        "cost_fiat": 0.012,
        "charging": {"voice_surcharge_charge": 4},
    }
    payload: dict[str, Any] = {
        "agent_id": "agent_fixture",
        "conversation_id": "conv_fixture",
        "status": "done",
        "metadata": metadata,
        "transcript": [{"message": "must not be forwarded"}],
    }
    if change == "zero":
        metadata.update(cost=0, cost_fiat=0, charging={"voice_surcharge_charge": 0})
    if change == "pending":
        payload["status"] = "processing"
    if change == "foreign_agent":
        payload["agent_id"] = "agent_other"
    if change == "foreign_conversation":
        payload["conversation_id"] = "conv_other"
    if change == "missing":
        payload.pop("metadata")
    if change == "negative":
        metadata["cost"] = -1
    if change == "boolean":
        metadata["cost"] = True
    if change == "invalid_usd":
        metadata["cost_fiat"] = "0.012"
    seen: list[ProviderUsage] = []
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503 if change == "failure" else 200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        provider = ElevenLabsProvider("fixture", "agent_fixture", http=http)
        assert await provider.confirm_closed("conv_fixture", seen.append) is confirmed
    assert len(requests) == 1
    assert bool(seen) is receipt
    if receipt:
        value = seen[0].model_dump()
        assert set(value) == {"provider", "credits", "voice_surcharge_credits", "usd"}
        assert value["credits"] == (0 if change == "zero" else 296)
        assert value["voice_surcharge_credits"] == (0 if change == "zero" else 4)
