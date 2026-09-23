"""GA Realtime over WebRTC: SDP exchange, server-owned delegate_task tool, bounded sideband."""

import asyncio
import json
import re
from contextlib import suppress
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel, Field, ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from .models import (
    COMMENTARY_MAX_BYTES,
    ClientCredential,
    DelegationRequested,
    ProviderCapabilities,
    ProviderCommand,
    ProviderError,
    ProviderEvent,
    ProviderFailure,
    SessionConfig,
    SessionStarted,
    SpeechStarted,
    Transcript,
    UnsupportedCapability,
    WebRTCAnswer,
)
from .openai import OpenAILiveConnection

CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,256}")
DELEGATE_TASK_TOOL = {
    "type": "function",
    "name": "delegate_task",
    "description": "Delegate arithmetic and project questions to the worker.",
    "parameters": {
        "type": "object",
        "properties": {"goal": {"type": "string"}},
        "required": ["goal"],
        "additionalProperties": False,
    },
}


class WireEvent(BaseModel):
    type: str
    delta: str = Field(default="", max_length=65536)
    transcript: str = Field(default="", max_length=65536)
    name: str = ""
    call_id: str = Field(default="", max_length=256)
    arguments: str = Field(default="{}", max_length=8192)


class TaskArguments(BaseModel):
    goal: str = Field(min_length=1, max_length=2048)


def normalize_event(raw: str | bytes) -> ProviderEvent | None:
    event = WireEvent.model_validate_json(raw)
    if event.type == "session.created":
        return SessionStarted()
    if event.type == "input_audio_buffer.speech_started":
        return SpeechStarted()
    if event.type == "error":
        return ProviderFailure()
    if event.type == "response.function_call_arguments.done":
        if event.name != "delegate_task" or not event.call_id:
            return ProviderFailure("unsupported_tool")
        args = TaskArguments.model_validate_json(event.arguments)
        return DelegationRequested(event.call_id, goal=args.goal)
    if event.type in {
        "conversation.item.input_audio_transcription.completed",
        "response.output_audio_transcript.done",
    }:
        return Transcript(
            "user" if event.type.startswith("conversation") else "assistant",
            event.transcript,
            0,
            0,
            committed=True,
        )
    return None


class RealtimeWebRTCConnection(OpenAILiveConnection):
    """Reuse the bounded single-reader transport; translate only Realtime commands."""

    normalize = staticmethod(normalize_event)

    def __init__(
        self, answer: WebRTCAnswer, socket: ClientConnection, provider: "RealtimeWebRTCProvider"
    ) -> None:
        self._provider = provider
        super().__init__(answer, socket, 5)

    async def send(self, command: ProviderCommand) -> None:
        if self._closed or len(command.content.encode()) > COMMENTARY_MAX_BYTES:
            raise ProviderError("Connection closed or result budget exceeded")
        try:
            async with asyncio.timeout(2):
                await self._socket.send(
                    json.dumps(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": command.delegation_id,
                                "output": command.content,
                            },
                        }
                    )
                )
                await self._socket.send(json.dumps({"type": "response.create"}))
        except (TimeoutError, WebSocketException, OSError) as exc:
            raise ProviderError("Realtime command failed") from exc

    async def aclose(self) -> bool:
        async with self._close_lock:
            if self._closed:
                return self._finalized.is_set()
            self._closed = True
            try:
                if await self._provider.hangup(self.answer.session_id):
                    self._finalized.set()
            finally:
                await self._socket.close()
                self._reader.cancel()
                with suppress(asyncio.CancelledError):
                    await self._reader
            return self._finalized.is_set()


class RealtimeWebRTCProvider:
    """Exchange SDP once, validate call identity and attach before replaying text.

    OpenAI and Azure share this wire contract. Subclasses supply only the endpoint,
    the authentication headers and a display name used in error messages.
    """

    model = "gpt-realtime"
    voice = "marin"
    capabilities = ProviderCapabilities(
        client_delegation=False, text_replay=True, transcript_timing=False
    )
    name = "Realtime"

    def __init__(
        self, endpoint: str, headers: dict[str, str], http: httpx.AsyncClient | None = None
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._headers = dict(headers)
        self._http = http or httpx.AsyncClient(timeout=15)

    def default_config(
        self, instructions: str, history: tuple[tuple[str, str], ...] = ()
    ) -> SessionConfig:
        """Build startup configuration using this provider's model and voice."""
        return SessionConfig(self.model, self.voice, instructions, history)

    async def issue_client_credential(self, config: SessionConfig) -> ClientCredential:
        raise UnsupportedCapability("Use server-mediated SDP to retain lifecycle ownership")

    async def _attach(self, call_id: str) -> ClientConnection:
        return await connect(
            self._endpoint.replace("https://", "wss://", 1) + "?call_id=" + quote(call_id, safe=""),
            additional_headers=self._headers,
            max_queue=16,
            max_size=1048576,
            write_limit=32768,
            open_timeout=8,
            close_timeout=2,
        )

    async def hangup(self, call_id: str) -> bool:
        try:
            async with asyncio.timeout(5):
                response = await self._http.post(
                    f"{self._endpoint}/calls/{quote(call_id, safe='')}/hangup",
                    headers=self._headers,
                )
                response.raise_for_status()
                return True
        except (httpx.HTTPError, TimeoutError):
            return False

    def _session(self, config: SessionConfig) -> dict[str, object]:
        return {
            "type": "realtime",
            "model": config.model,
            "instructions": config.instructions,
            "audio": {
                "output": {"voice": config.voice},
                "input": {"transcription": {"model": "whisper-1"}},
            },
            "tools": [DELEGATE_TASK_TOOL],
        }

    async def connect(self, *, config: SessionConfig, offer_sdp: str) -> RealtimeWebRTCConnection:
        call_id = ""
        socket: ClientConnection | None = None
        try:
            session = json.dumps(self._session(config))
            response = await self._http.post(
                self._endpoint + "/calls",
                headers=self._headers,
                files={"sdp": (None, offer_sdp), "session": (None, session)},
            )
            response.raise_for_status()
            candidate = urlparse(response.headers.get("location", "")).path.rsplit("/", 1)[-1]
            if not CALL_ID.fullmatch(candidate):
                raise ProviderError(
                    f"{self.name} returned an invalid call identity; cleanup unconfirmed"
                )
            call_id = candidate
            if not response.text.startswith("v=0") or len(response.content) > 65536:
                raise ProviderError(f"{self.name} returned an invalid SDP answer")
            socket = await self._attach(call_id)
            async with asyncio.timeout(5):
                for role, content in config.history:
                    await socket.send(
                        json.dumps(
                            {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "message",
                                    "role": role,
                                    "content": [
                                        {
                                            "type": "input_text" if role == "user" else "text",
                                            "text": content,
                                        }
                                    ],
                                },
                            }
                        )
                    )
            return RealtimeWebRTCConnection(WebRTCAnswer(call_id, response.text), socket, self)
        except (
            httpx.HTTPError,
            ValidationError,
            WebSocketException,
            OSError,
            TimeoutError,
            ProviderError,
            asyncio.CancelledError,
        ) as exc:
            if socket is not None:
                await socket.close()
            if call_id:
                await self.hangup(call_id)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ProviderError(
                f"{self.name} connection failed; check server configuration"
            ) from exc

    async def aclose(self) -> None:
        await self._http.aclose()
