"""Deterministic offline control provider; it does not simulate WebRTC audio."""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from .models import (
    ClientCredential,
    ProviderCapabilities,
    ProviderCommand,
    ProviderEvent,
    SessionClosed,
    SessionConfig,
    UnsupportedCapability,
    WebRTCAnswer,
)


class FakeConnection:
    """Inject typed events and inspect commands without network access."""

    def __init__(self) -> None:
        self.answer = WebRTCAnswer(str(uuid4()), "v=0\r\n")
        self.queue: asyncio.Queue[ProviderEvent] = asyncio.Queue(maxsize=64)
        self.commands: list[ProviderCommand] = []
        self.closed = False

    async def events(self) -> AsyncIterator[ProviderEvent]:
        """Yield fixture events until explicitly closed."""
        while True:
            event = await self.queue.get()
            yield event
            if isinstance(event, SessionClosed):
                return

    async def send(self, command: ProviderCommand) -> None:
        """Record commands for scenario assertions."""
        self.commands.append(command)

    async def aclose(self) -> bool:
        """Finalize the fake immediately."""
        self.closed = True
        return True


class FakeProvider:
    """An injectable provider for lifecycle and error-path tests."""

    capabilities = ProviderCapabilities(transcript_timing=True)

    def __init__(self) -> None:
        self.connections: list[FakeConnection] = []

    async def connect(self, *, config: SessionConfig, offer_sdp: str) -> FakeConnection:
        """Create an independently controllable fake connection."""
        connection = FakeConnection()
        self.connections.append(connection)
        return connection

    async def issue_client_credential(self, config: SessionConfig) -> ClientCredential:
        """Do not issue credentials that could be mistaken for real ones."""
        raise UnsupportedCapability("Fake provider has no browser credentials")

    async def aclose(self) -> None:
        """The fake owns no shared external resources."""
