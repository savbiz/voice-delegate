"""Development-only Agents bootstrap and unsupported-transport contracts, never live."""

import asyncio
import json

import httpx
import pytest
from conftest import ASGIClientFactory
from pydantic import SecretStr, ValidationError
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.providers.elevenlabs import MAX_RESPONSE_BYTES, ElevenLabsProvider
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import ProviderError, UnsupportedCapability


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


async def test_bootstrap_route_is_owned_one_shot_and_blocks_sdp_setup(
    asgi_client: ASGIClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        elevenlabs_enabled=True,
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

    monkeypatch.setattr(ElevenLabsProvider, "validate_agent", validate)
    monkeypatch.setattr(ElevenLabsProvider, "prepare_browser", prepare)
    app = create_app(settings, FakeProvider())
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
        closed = await client.post(f"/api/sessions/{session['id']}/close")
        assert not closed.json()["finalized"]


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
        elevenlabs_enabled=True,
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
    async with asgi_client(create_app(settings, FakeProvider())) as client:
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
    "change", ["none", "public", "sync", "extra_tool", "duration", "overrides"]
)
async def test_agent_policy_is_validated_before_credentials(change: str) -> None:
    tool = {
        "type": "client",
        "name": "delegate_task",
        "expects_response": True,
        "execution_mode": "async",
        "response_timeout_secs": 120,
        "parameters": {"required": ["goal"], "properties": {"goal": {"type": "string"}}},
    }
    agent = {
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
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=agent))
    ) as http:
        provider = ElevenLabsProvider("fixture", "agent_fixture", http=http)
        if change == "none":
            await provider.validate_agent(300)
        else:
            with pytest.raises(ProviderError, match="private async"):
                await provider.validate_agent(300)


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


async def test_sdk_uses_existing_worker_scheduler_with_owned_routes(
    asgi_client: ASGIClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from voice_delegate.api.routes import build_router
    from voice_delegate.providers.elevenlabs import BrowserBootstrap
    from voice_delegate.session.manager import SessionManager
    from voice_delegate.session.models import SessionError

    provider = ElevenLabsProvider("fixture", "agent_fixture")

    async def validate(ttl: float) -> None:
        pass

    async def bootstrap() -> BrowserBootstrap:
        return BrowserBootstrap("conv_fixture", "ephemeral-fixture")

    monkeypatch.setattr(provider, "validate_agent", validate)
    monkeypatch.setattr(provider, "prepare_browser", bootstrap)

    async def confirm(identity: str) -> bool:
        return False

    monkeypatch.setattr(provider, "confirm_closed", confirm)
    manager = SessionManager(FakeProvider(), Settings())
    app = FastAPI()

    async def session_error(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, SessionError)
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    app.add_exception_handler(SessionError, session_error)
    app.include_router(build_router(manager, elevenlabs=provider))
    session = manager.create()
    root = f"/api/sessions/{session.id}"
    try:
        async with asgi_client(app) as client:
            client.headers.update({"Origin": "http://localhost:5173", "X-Session-Key": session.key})
            assert (await client.post(root + "/elevenlabs/bootstrap")).status_code == 200
            assert (
                await client.post(
                    root + "/elevenlabs/delegate", json={"call_id": "one", "goal": "calculate 2+2"}
                )
            ).status_code == 409
            assert (
                await client.post(
                    root + "/elevenlabs/events",
                    json={"kind": "connected", "sequence": 0, "conversation_id": "other"},
                )
            ).status_code == 409
            assert (
                await client.post(
                    root + "/elevenlabs/events",
                    json={"kind": "connected", "sequence": 0, "conversation_id": "conv_fixture"},
                )
            ).status_code == 200
            assert (
                await client.post(
                    root + "/elevenlabs/delegate", json={"call_id": "one", "goal": "calculate 2+2"}
                )
            ).status_code == 202
            from test_support import eventually

            await eventually(lambda: session.delegation.status == "completed")
            result = (
                await client.post(root + "/elevenlabs/result", json={"call_id": "one"})
            ).json()
            assert result["status"] == "ready"
            assert "4" in result["text"]
            client.headers["X-Session-Key"] = "wrong"
            assert (
                await client.post(root + "/elevenlabs/result", json={"call_id": "one"})
            ).status_code == 404
    finally:
        await manager.aclose()
        await provider.aclose()


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
