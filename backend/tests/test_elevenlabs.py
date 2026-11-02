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


def test_preview_requires_credentials_and_stays_out_of_production() -> None:
    assert not Settings().elevenlabs_enabled
    with pytest.raises(ValidationError, match="requires ELEVENLABS_API_KEY"):
        Settings(elevenlabs_enabled=True)
    with pytest.raises(ValidationError, match="development-only"):
        Settings(environment="production", elevenlabs_enabled=True)


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
