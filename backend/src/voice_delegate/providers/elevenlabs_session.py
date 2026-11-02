"""Owned SDK control boundary; browser reports never prove provider finalization."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from .models import (
    Commentary,
    DelegationRequested,
    ProviderError,
    ProviderEvent,
    SessionStarted,
    UnsupportedCapability,
    WebRTCAnswer,
)


@dataclass
class SDKCall:
    goal: str
    result: str | None = None


class ElevenLabsConnection:
    """Bounded client-tool correlation and the existing server delivery scheduler."""

    def __init__(self, conversation_id: str, confirm_close: Callable[[], Awaitable[bool]]) -> None:
        self.conversation_id = conversation_id
        self.confirm_close = confirm_close
        self.queue: asyncio.Queue[ProviderEvent | None] = asyncio.Queue(maxsize=64)
        self.calls: dict[str, SDKCall] = {}
        self.started = False
        self.closed = False
        self.sequence = -1
        self.events_received = 0

    @property
    def answer(self) -> WebRTCAnswer:
        message = "SDK-managed media does not expose an SDP answer"
        raise UnsupportedCapability(message)

    def emit(self, event: ProviderEvent) -> None:
        if self.closed:
            message = "SDK session is closed"
            raise ProviderError(message)
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            message = "SDK event capacity reached"
            raise ProviderError(message) from None

    def start(self) -> None:
        if not self.started:
            self.emit(SessionStarted())
            self.started = True

    def delegate(self, identity: str, goal: str) -> None:
        previous = self.calls.get(identity)
        if previous is not None:
            if previous.goal != goal:
                message = "SDK call identity was reused"
                raise ProviderError(message)
            return
        if len(self.calls) >= 64:
            message = "SDK call capacity reached"
            raise ProviderError(message)
        self.emit(DelegationRequested(identity, goal=goal))
        self.calls[identity] = SDKCall(goal)

    async def events(self) -> AsyncIterator[ProviderEvent]:
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def send(self, command: Commentary) -> None:
        call = self.calls.get(command.delegation_id)
        if self.closed or call is None:
            message = "SDK result has no admitted call"
            raise ProviderError(message)
        if len(command.content.encode()) > 500:
            message = "SDK result exceeds the delivery budget"
            raise ProviderError(message)
        if call.result is None:
            call.result = (
                "Task cancelled or no longer deliverable."
                if command.settle_only
                else command.content
            )

    async def aclose(self) -> bool:
        if self.closed:
            return False
        self.closed = True
        for call in self.calls.values():
            if call.result is None:
                call.result = "Session ended; task cancelled."
        # Do not leave an event consumer blocked, even after queue exhaustion.
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queue.put_nowait(None)
        return await self.confirm_close() if self.started else False
