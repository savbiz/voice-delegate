"""Contracts isolating media setup and control from application lifecycle."""

from collections.abc import AsyncIterator
from typing import Protocol

from .models import (
    ClientCredential,
    ProviderCapabilities,
    ProviderCommand,
    ProviderEvent,
    SessionConfig,
    WebRTCAnswer,
)


class SidebandSocket(Protocol):
    """The text-control subset shared by WebSocket transports and offline fixtures."""

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...

    async def send(self, message: str) -> None: ...

    async def close(self) -> None: ...


class RealtimeConnection(Protocol):
    """An established call with a single server-side event consumer."""

    @property
    def answer(self) -> WebRTCAnswer: ...

    def events(self) -> AsyncIterator[ProviderEvent]: ...

    async def send(self, command: ProviderCommand) -> None: ...

    async def aclose(self) -> bool:
        """Close idempotently; report whether finalization was confirmed."""
        ...


class RealtimeProvider(Protocol):
    """Factory shared by application sessions."""

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def default_config(
        self, instructions: str, history: tuple[tuple[str, str], ...] = ()
    ) -> SessionConfig: ...

    async def issue_client_credential(self, config: SessionConfig) -> ClientCredential: ...

    async def connect(self, *, config: SessionConfig, offer_sdp: str) -> RealtimeConnection: ...

    async def aclose(self) -> None: ...
