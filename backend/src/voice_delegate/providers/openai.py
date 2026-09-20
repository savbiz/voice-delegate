"""Translate the public GPT-Live WebRTC and sideband protocols."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from urllib.parse import quote
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from .models import (
    ClientCredential,
    DelegationRequested,
    ProviderCapabilities,
    ProviderCommand,
    ProviderError,
    ProviderEvent,
    ProviderFailure,
    SessionClosed,
    SessionConfig,
    SessionStarted,
    Transcript,
    UnsupportedCapability,
    WebRTCAnswer,
)

logger = logging.getLogger(__name__)


class _Session(BaseModel):
    id: str = Field(min_length=1, max_length=256)


class _Transport(BaseModel):
    sdp: str = Field(min_length=1, max_length=65536)


class _Created(BaseModel):
    session: _Session
    transport: _Transport


class _Delegation(BaseModel):
    id: str = Field(max_length=256)


class _WireEvent(BaseModel):
    type: str
    delta: str = Field(default="", max_length=1048576)
    start_ms: float = Field(default=0, ge=0, allow_inf_nan=False)
    end_ms: float = Field(default=0, ge=0, allow_inf_nan=False)
    delegation: _Delegation | None = None
    reason: str = "unknown"
    offset_ms: float = Field(default=0, ge=0, allow_inf_nan=False)


def normalize_event(raw: str | bytes) -> ProviderEvent | None:
    """Validate events and immediately discard reflected audio and unknown events."""
    event = _WireEvent.model_validate_json(raw)
    match event.type:
        case "session.started":
            return SessionStarted()
        case "session.closed":
            return SessionClosed(event.reason)
        case "error":
            return ProviderFailure()
        case "session.delegation.created" if event.delegation is not None:
            return DelegationRequested(event.delegation.id, event.offset_ms)
        case "session.input_transcript.delta" | "session.output_transcript.delta":
            return Transcript(
                "user" if event.type == "session.input_transcript.delta" else "assistant",
                event.delta,
                event.start_ms,
                event.end_ms,
            )
    return None


class OpenAILiveConnection:
    """Own one sideband reader, a bounded event queue, and graceful finalization."""

    def __init__(
        self, answer: WebRTCAnswer, socket: ClientConnection, close_timeout: float
    ) -> None:
        self.answer = answer
        self._socket = socket
        self._close_timeout = close_timeout
        self._queue: asyncio.Queue[ProviderEvent] = asyncio.Queue(maxsize=64)
        self._finalized = asyncio.Event()
        self._closed = False
        self._failed = False
        self._close_lock = asyncio.Lock()
        self._reader = asyncio.create_task(self._read(), name="live-sideband-reader")

    normalize = staticmethod(normalize_event)

    async def _read(self) -> None:
        try:
            async for raw in self._socket:
                event = self.normalize(raw)
                if isinstance(event, SessionClosed):
                    self._finalized.set()
                if event is not None:
                    self._queue.put_nowait(event)
                if self._finalized.is_set():
                    return
        except (WebSocketException, OSError, ValidationError, asyncio.QueueFull):
            self._failed = True
        finally:
            if not self._finalized.is_set():
                self._failed = True

    async def events(self) -> AsyncIterator[ProviderEvent]:
        """Drain without unbounded polling or a second WebSocket consumer."""
        while True:
            if not self._queue.empty():
                yield self._queue.get_nowait()
                continue
            if self._reader.done():
                if self._failed:
                    raise ProviderError("Provider event stream ended unexpectedly")
                return
            pending = asyncio.create_task(self._queue.get())
            try:
                done, _ = await asyncio.wait(
                    {pending, self._reader}, return_when=asyncio.FIRST_COMPLETED
                )
                if pending in done:
                    yield pending.result()
            finally:
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending

    async def send(self, command: ProviderCommand) -> None:
        """Send worker commentary with a conservative provider wire budget."""
        if self._closed:
            raise ProviderError("Connection is closing")
        # UTF-8 bytes conservatively upper-bound byte-level tokenizer output.
        if len(command.content.encode()) > 500:
            raise ProviderError("Commentary wire budget exceeded")
        try:
            async with asyncio.timeout(2):
                await self._socket.send(
                    json.dumps(
                        {
                            "type": "session.commentary.append",
                            "event_id": str(uuid4()),
                            "delegation_id": command.delegation_id,
                            "content": command.content,
                        }
                    )
                )
        except (TimeoutError, WebSocketException, OSError) as exc:
            raise ProviderError("Provider command failed") from exc

    async def aclose(self) -> bool:
        """Keep the receiver alive until finalization or a bounded deadline."""
        async with self._close_lock:
            if self._closed:
                return self._finalized.is_set()
            self._closed = True
            try:
                if not self._finalized.is_set():
                    async with asyncio.timeout(self._close_timeout):
                        await self._socket.send(json.dumps({"type": "session.close"}))
                        await self._finalized.wait()
            except (TimeoutError, WebSocketException, OSError):
                logger.warning("Provider finalization unconfirmed")
            finally:
                await self._socket.close()
                self._reader.cancel()
                with suppress(asyncio.CancelledError):
                    await self._reader
            return self._finalized.is_set()


class OpenAILiveProvider:
    """Create sessions with server credentials; never retry billable creation."""

    capabilities = ProviderCapabilities()

    def __init__(
        self, api_key: str, close_timeout: float = 5, http: httpx.AsyncClient | None = None
    ) -> None:
        self._api_key = api_key
        self._close_timeout = close_timeout
        self._http = http or httpx.AsyncClient(timeout=15)

    async def issue_client_credential(self, config: SessionConfig) -> ClientCredential:
        """Live's documented WebRTC path uses server-mediated SDP creation."""
        raise UnsupportedCapability("GPT-Live uses the SDP endpoint; no ephemeral token adapter")

    async def _attach(self, session_id: str) -> ClientConnection:
        return await connect(
            f"wss://api.openai.com/v1/live/sessions/{quote(session_id, safe='')}/attach",
            additional_headers={"Authorization": f"Bearer {self._api_key}"},
            max_queue=16,
            max_size=1048576,
            write_limit=32768,
            open_timeout=8,
            close_timeout=2,
        )

    async def connect(self, *, config: SessionConfig, offer_sdp: str) -> OpenAILiveConnection:
        """Exchange JSON SDP and attach before returning the browser's answer."""
        if not self._api_key:
            raise ProviderError("Set OPENAI_API_KEY on the server")
        answer: WebRTCAnswer | None = None
        try:
            response = await self._http.post(
                "https://api.openai.com/v1/live/sessions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "session": {
                        "model": config.model,
                        "instructions": config.instructions,
                        "audio": {"output": {"voice": config.voice}},
                        "delegation": {"type": "client"},
                        "store": False,
                    },
                    "transport": {"type": "webrtc", "sdp": offer_sdp},
                },
            )
            response.raise_for_status()
            created = _Created.model_validate_json(response.content)
            answer = WebRTCAnswer(created.session.id, created.transport.sdp)
            socket = await self._attach(answer.session_id)
            return OpenAILiveConnection(answer, socket, self._close_timeout)
        except (
            httpx.HTTPError,
            ValidationError,
            WebSocketException,
            OSError,
            TimeoutError,
            asyncio.CancelledError,
        ) as exc:
            if answer is not None:
                # Recover control solely to close a partially initialized call.
                try:
                    async with asyncio.timeout(10):
                        socket = await self._attach(answer.session_id)
                        abandoned = OpenAILiveConnection(answer, socket, self._close_timeout)
                        await abandoned.aclose()
                except (TimeoutError, WebSocketException, OSError):
                    logger.error("Could not recover sideband for cleanup; finalization unconfirmed")
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ProviderError(
                "GPT-Live connection failed; check account access and configuration"
            ) from exc

    async def aclose(self) -> None:
        """Release the shared HTTP client after session shutdown."""
        await self._http.aclose()
