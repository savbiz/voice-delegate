"""Bound session lifetimes and give every connection one cleanup owner."""

import asyncio
import logging
import secrets
import time
from collections.abc import Callable
from contextlib import suppress
from uuid import uuid4

from voice_delegate.config import Settings
from voice_delegate.providers.base import RealtimeProvider
from voice_delegate.providers.models import (
    Commentary,
    DelegationRequested,
    ProviderError,
    ProviderFailure,
    SessionClosed,
    SessionConfig,
    WebRTCAnswer,
)

from .models import Session, SessionError

logger = logging.getLogger(__name__)
M1_INSTRUCTIONS = (
    "You are a concise voice assistant. Speak naturally in the user's language. "
    "This demo supports conversation only. External tools and task execution are not "
    "available yet. Never claim to have searched, accessed external data, or completed an action."
)


class SessionManager:
    """Single-process registry with bounded capacity and monotonic deadlines."""

    def __init__(
        self,
        provider: RealtimeProvider,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.clock = clock
        self.sessions: dict[str, Session] = {}
        self._shutting_down = False

    def create(self) -> Session:
        """Reserve capacity atomically before any billable provider request."""
        if self._shutting_down:
            raise SessionError(503, "Service shutting down")
        if len(self.sessions) >= self.settings.max_sessions:
            raise SessionError(429, "Session capacity reached")
        now = self.clock()
        session = Session(str(uuid4()), secrets.token_urlsafe(32), now, now)
        self.sessions[session.id] = session
        return session

    def get(self, session_id: str, key: str) -> Session:
        """Resolve ownership without disclosing whether another session exists."""
        session = self.sessions.get(session_id)
        if session is None or not secrets.compare_digest(session.key.encode(), key.encode()):
            raise SessionError(404, "Session not found")
        return session

    def heartbeat(self, session: Session) -> None:
        """Refresh browser liveness; never extend the absolute session deadline."""
        session.last_heartbeat = self.clock()

    def config(self) -> SessionConfig:
        """Build trusted provider configuration."""
        return SessionConfig(self.settings.model, self.settings.voice, M1_INSTRUCTIONS)

    async def connect(self, session: Session, offer_sdp: str) -> WebRTCAnswer:
        """Prevent duplicate offers from creating multiple billable calls."""
        async with session.lock:
            if session.state != "created":
                raise SessionError(409, "Session already connected or closed")
            session.state = "connecting"
            try:
                async with asyncio.timeout(self.settings.connect_timeout_seconds):
                    session.connection = await self.provider.connect(
                        config=self.config(), offer_sdp=offer_sdp
                    )
            except (ProviderError, TimeoutError, asyncio.CancelledError):
                session.state = "closed"
                self.sessions.pop(session.id, None)
                raise
            session.state = "connected"
            session.watcher = asyncio.create_task(self._watch(session), name="session-events")
            return session.connection.answer

    async def _watch(self, session: Session) -> None:
        connection = session.connection
        assert connection is not None
        try:
            async for event in connection.events():
                if isinstance(event, SessionClosed):
                    session.finalized = True
                    break
                if session.state == "closing":
                    continue
                if isinstance(event, ProviderFailure):
                    break
                if isinstance(event, DelegationRequested):
                    await connection.send(
                        Commentary(
                            event.delegation_id,
                            "Task execution is unavailable in this milestone. No action was taken.",
                        )
                    )
        except ProviderError:
            logger.warning("Session provider stream failed")
        finally:
            if session.state not in {"closing", "closed"}:
                await self.close(session)

    async def close(self, session: Session) -> bool:
        """Idempotently close upstream before canceling the event consumer."""
        async with session.lock:
            if session.state == "closed":
                return session.finalized
            session.state = "closing"
            try:
                if session.connection is not None:
                    session.finalized = await session.connection.aclose() or session.finalized
            finally:
                watcher = session.watcher
                if watcher is not None and watcher is not asyncio.current_task():
                    watcher.cancel()
                    with suppress(asyncio.CancelledError):
                        await watcher
                session.state = "closed"
                self.sessions.pop(session.id, None)
            return session.finalized

    async def expire(self) -> None:
        """Expire abandoned setup, lost browsers, and absolute time budgets."""
        now = self.clock()
        expired = [
            s
            for s in self.sessions.values()
            if (
                now - s.created_at >= self.settings.session_ttl_seconds
                or now - s.last_heartbeat >= self.settings.heartbeat_timeout_seconds
            )
        ]
        await asyncio.gather(*(self.close(s) for s in expired))

    async def sweep(self) -> None:
        """Run a cancellable janitor; expiry has at most one second granularity."""
        while True:
            await asyncio.sleep(1)
            await self.expire()

    async def aclose(self) -> None:
        """Drain all owned sessions before releasing the provider."""
        self._shutting_down = True
        await asyncio.gather(*(self.close(s) for s in list(self.sessions.values())))
        await self.provider.aclose()
