"""In-memory session state; each session belongs to one process in M1."""

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from voice_delegate.delegation.history import History
from voice_delegate.delegation.runner import DelegationState
from voice_delegate.providers.base import RealtimeConnection


@dataclass
class Session:
    """Own the control connection, capability key, and lifecycle tasks."""

    id: str
    key: str = field(repr=False)
    created_at: float
    last_heartbeat: float
    state: Literal["created", "connecting", "connected", "closing", "closed"] = "created"
    connection: RealtimeConnection | None = None
    watcher: asyncio.Task[None] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    finalized: bool = False
    history: History = field(default_factory=History)
    delegation: DelegationState = field(default_factory=DelegationState)


class SessionError(Exception):
    """An application error with a safe HTTP status and message."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
