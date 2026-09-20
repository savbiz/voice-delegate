"""Offline fallback scenarios: bounded history, one attempt, deadlines and cleanup."""

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from voice_delegate.config import Settings
from voice_delegate.providers.azure import AzureRealtimeProvider, normalize_event
from voice_delegate.providers.fake import FakeConnection, FakeProvider
from voice_delegate.providers.models import (
    DelegationRequested,
    ProviderCapabilities,
    ProviderError,
    ProviderEvent,
    ProviderFailure,
    SessionConfig,
    Transcript,
)
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import SessionError


class ReplayProvider(FakeProvider):
    capabilities = ProviderCapabilities(text_replay=True)

    def __init__(self) -> None:
        super().__init__()
        self.configs: list[SessionConfig] = []

    async def connect(self, *, config: SessionConfig, offer_sdp: str) -> FakeConnection:
        self.configs.append(config)
        return await super().connect(config=config, offer_sdp=offer_sdp)


async def test_failure_preserves_owner_and_replays_only_sealed_history() -> None:
    primary, fallback = FakeProvider(), ReplayProvider()
    manager = SessionManager(primary, Settings(), fallback=fallback)
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    events: list[ProviderEvent] = [
        Transcript("user", "hello", 0, 100),
        Transcript("assistant", "unfinished", 101, 200),
        ProviderFailure(),
    ]
    for event in events:
        primary.connections[0].queue.put_nowait(event)
    assert session.watcher is not None
    await session.watcher
    assert session.state == "reconnecting"
    assert manager.get(session.id, session.key) is session
    await manager.reconnect(session, "v=0\r\n", 0)
    assert fallback.configs[0].history == (("user", "hello"),)
    assert primary.connections[0].closed
    assert session.generation == 1
    with pytest.raises(SessionError) as duplicate:
        await manager.reconnect(session, "v=0\r\n", 0)
    assert duplicate.value.status == 409
    assert len(fallback.connections) == 1
    fallback.connections[0].queue.put_nowait(ProviderFailure())
    assert session.watcher is not None
    await session.watcher
    assert not manager.sessions
    await manager.aclose()


async def test_reconnect_timeout_does_not_reset_lifetime_or_retry() -> None:
    class Slow(ReplayProvider):
        async def connect(self, *, config: SessionConfig, offer_sdp: str) -> FakeConnection:
            await asyncio.Event().wait()
            raise AssertionError

    manager = SessionManager(
        FakeProvider(), Settings(connect_timeout_seconds=0.01), fallback=Slow()
    )
    session = manager.create()
    created = session.created_at
    await manager.connect(session, "v=0\r\n")
    with pytest.raises(TimeoutError):
        await manager.reconnect(session, "v=0\r\n", 0)
    assert session.created_at == created
    assert session.fallback_used
    assert not manager.sessions
    await manager.aclose()


async def test_concurrent_fallback_creates_one_call() -> None:
    fallback = ReplayProvider()
    manager = SessionManager(FakeProvider(), Settings(), fallback=fallback)
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    results = await asyncio.gather(
        *(manager.reconnect(session, "v=0\r\n", 0) for _ in range(2)), return_exceptions=True
    )
    assert sum(isinstance(r, SessionError) for r in results) == 1
    assert len(fallback.connections) == 1
    await manager.aclose()


def test_azure_normalization_and_untrusted_function_arguments() -> None:
    event = normalize_event(
        json.dumps(
            {
                "type": "response.function_call_arguments.done",
                "name": "delegate_task",
                "call_id": "call-1",
                "arguments": '{"goal":"2+2"}',
            }
        )
    )
    assert isinstance(event, DelegationRequested)
    assert event.goal == "2+2"
    assert isinstance(normalize_event('{"type":"error"}'), ProviderFailure)
    transcript = normalize_event(
        json.dumps({"type": "response.output_audio_transcript.done", "transcript": "four"})
    )
    assert isinstance(transcript, Transcript) and transcript.committed


async def test_azure_attach_failure_hangs_up_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/hangup"):
            return httpx.Response(200)
        return httpx.Response(201, text="v=0\r\n", headers={"Location": "/calls/rtc_1"})

    provider = AzureRealtimeProvider(
        "https://example.openai.azure.com",
        "secret",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise OSError("private detail")

    monkeypatch.setattr(provider, "_attach", broken)
    with pytest.raises(ProviderError, match="Azure connection failed"):
        await provider.connect(
            config=SessionConfig("deployment", "marin", "instructions"), offer_sdp="v=0\r\n"
        )
    assert [r.url.path for r in requests] == [
        "/openai/v1/realtime/calls",
        "/openai/v1/realtime/calls/rtc_1/hangup",
    ]
    await provider.aclose()


def test_fallback_rejects_non_azure_endpoint() -> None:
    with pytest.raises(ValueError, match="HTTPS Azure"):
        Settings(
            fallback_enabled=True,
            azure_endpoint="http://localhost",
            azure_api_key=SecretStr("secret"),
        )


async def test_azure_success_replays_text_returns_tool_result_and_hangs_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import AsyncIterator

    from voice_delegate.providers.models import Commentary

    class Socket:
        def __init__(self) -> None:
            self.sent: list[dict[str, Any]] = []
            self.closed = False

        async def send(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

        async def close(self) -> None:
            self.closed = True

        async def __aiter__(self) -> AsyncIterator[str]:
            await asyncio.Event().wait()
            yield ""

    socket = Socket()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers["api-key"] == "secret"
        if request.url.path.endswith("/hangup"):
            return httpx.Response(200)
        assert b"delegate_task" in request.content
        return httpx.Response(201, text="v=0\r\n", headers={"Location": "/calls/rtc_test"})

    provider = AzureRealtimeProvider(
        "https://example.openai.azure.com",
        "secret",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    async def attach(call_id: str) -> Any:
        assert call_id == "rtc_test"
        return socket

    monkeypatch.setattr(provider, "_attach", attach)
    connection = await provider.connect(
        config=SessionConfig("deployment", "marin", "trusted", (("user", "untrusted text"),)),
        offer_sdp="v=0\r\n",
    )
    assert socket.sent[0]["item"]["role"] == "user"
    assert socket.sent[0]["item"]["content"][0]["text"] == "untrusted text"
    await connection.send(Commentary("task-1", "4"))
    assert socket.sent[1]["item"]["type"] == "function_call_output"
    assert socket.sent[2] == {"type": "response.create"}
    assert await connection.aclose()
    assert await connection.aclose()
    assert socket.closed and len(calls) == 2
    await provider.aclose()
