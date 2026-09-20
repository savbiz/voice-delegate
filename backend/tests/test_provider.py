"""Verify public wire mappings, bounded control queues, and transport cleanup."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import cast

import httpx
import pytest
from pydantic import ValidationError
from voice_delegate.providers.models import (
    Commentary,
    DelegationRequested,
    ProviderError,
    SessionConfig,
    Transcript,
    WebRTCAnswer,
)
from voice_delegate.providers.openai import (
    OpenAILiveConnection,
    OpenAILiveProvider,
    normalize_event,
)
from websockets.asyncio.client import ClientConnection


def test_transcripts_preserve_fragments_and_timing() -> None:
    event = normalize_event(
        json.dumps(
            {
                "type": "session.input_transcript.delta",
                "delta": " yes, yes",
                "start_ms": 100,
                "end_ms": 300,
            }
        )
    )
    assert event == Transcript("user", " yes, yes", 100, 300)


def test_delegation_contains_identity_not_invented_task_text() -> None:
    event = normalize_event(
        json.dumps(
            {
                "type": "session.delegation.created",
                "offset_ms": 1000,
                "delegation": {"id": "item-1", "target": "client"},
            }
        )
    )
    assert event == DelegationRequested("item-1", 1000)


def test_audio_is_not_retained_in_application_queue() -> None:
    assert normalize_event('{"type":"session.output_audio.delta","delta":"AA=="}') is None


def test_malformed_events_fail_closed() -> None:
    with pytest.raises(ValidationError):
        normalize_event('{"type":"session.input_transcript.delta","start_ms": "NaN"}')


class MemorySocket:
    """A WebSocket-shaped fixture with explicit finalization behavior."""

    def __init__(self, finalize: bool = True) -> None:
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[str | bytes] = []
        self.finalize = finalize
        self.closed = False

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if json.loads(data)["type"] == "session.close" and self.finalize:
            self.incoming.put_nowait('{"type":"session.closed","reason":"close_requested"}')

    async def close(self) -> None:
        self.closed = True

    async def __aiter__(self) -> AsyncIterator[str]:
        while True:
            yield await self.incoming.get()


async def test_graceful_close_and_idempotency() -> None:
    socket = MemorySocket()
    connection = OpenAILiveConnection(
        WebRTCAnswer("id", "sdp"), cast(ClientConnection, socket), 0.05
    )
    await connection.send(Commentary("task", "No action was taken."))
    assert json.loads(socket.sent[0])["delegation_id"] == "task"
    assert await connection.aclose()
    assert await connection.aclose()
    assert len(socket.sent) == 2
    assert socket.closed


async def test_missing_final_event_is_not_reported_as_confirmed() -> None:
    socket = MemorySocket(finalize=False)
    connection = OpenAILiveConnection(
        WebRTCAnswer("id", "sdp"), cast(ClientConnection, socket), 0.01
    )
    assert not await connection.aclose()
    assert socket.closed


async def test_event_queue_overflow_fails_instead_of_growing() -> None:
    socket = MemorySocket(finalize=False)
    connection = OpenAILiveConnection(
        WebRTCAnswer("id", "sdp"), cast(ClientConnection, socket), 0.01
    )
    for _ in range(65):
        socket.incoming.put_nowait('{"type":"session.started"}')
    await asyncio.sleep(0)
    with pytest.raises(ProviderError):
        async for _event in connection.events():
            pass
    assert not await connection.aclose()


class FixtureProvider(OpenAILiveProvider):
    """Replace only the socket while exercising actual HTTP payload construction."""

    def __init__(self, http: httpx.AsyncClient, socket: MemorySocket) -> None:
        super().__init__("test-placeholder", http=http)
        self.socket = socket
        self.attached_id = ""

    async def _attach(self, session_id: str) -> ClientConnection:
        self.attached_id = session_id
        return cast(ClientConnection, self.socket)


async def test_creation_uses_live_json_and_client_delegation() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            201,
            json={
                "session": {"id": "live_example"},
                "transport": {"type": "webrtc", "sdp": "v=0\r\n"},
            },
        )

    provider = FixtureProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(respond)), MemorySocket()
    )
    connection = await provider.connect(
        config=SessionConfig("gpt-live-1", "marin", "Conversation only"), offer_sdp="v=0\r\n"
    )
    assert str(requests[0].url) == "https://api.openai.com/v1/live/sessions"
    body = json.loads(requests[0].content)
    assert body["session"]["delegation"] == {"type": "client"}
    assert body["transport"] == {"type": "webrtc", "sdp": "v=0\r\n"}
    assert body["session"]["store"] is False
    assert provider.attached_id == "live_example"
    await connection.aclose()
    await provider.aclose()


async def test_rejected_creation_does_not_retry_or_leak_response() -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, text="private upstream response")

    provider = FixtureProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(respond)), MemorySocket()
    )
    with pytest.raises(ProviderError) as error:
        await provider.connect(config=SessionConfig("gpt-live-1", "marin", ""), offer_sdp="v=0\r\n")
    assert "private upstream response" not in str(error.value)
    assert calls == 1
    await provider.aclose()
