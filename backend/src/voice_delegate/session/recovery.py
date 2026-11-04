"""One consented Azure recovery per session: suspend a failed call, then reconnect once."""

import asyncio
import logging
from typing import TYPE_CHECKING

from voice_delegate.providers.base import RealtimeConnection
from voice_delegate.providers.models import WebRTCAnswer

from .models import Session, SessionError

if TYPE_CHECKING:
    from .manager import SessionManager

logger = logging.getLogger(__name__)


class Recovery:
    """Owns the fallback rules; the manager keeps the session registry and event loop."""

    def __init__(self, manager: SessionManager) -> None:
        self.manager = manager

    def eligible(self, session: Session) -> bool:
        """Whether a failed primary call may wait for the browser's single reconnect."""
        return (
            self.manager.fallback is not None
            and session.adapter == "openai"
            and session.preferences.azure_recovery
            and not session.fallback_used
            and not session.finalized
        )

    async def suspend(self, session: Session, connection: RealtimeConnection) -> None:
        """Stop work on the failed call and close it while the browser prepares a new offer."""
        manager = self.manager
        if not manager.settings.intent_cancellation:
            manager.delegator.cancel(session.delegation)
        manager.intent.pause(session.portfolio)
        session.state = "reconnecting"
        try:
            session.previous_finalized = await connection.aclose()
        except Exception:
            session.previous_finalized = False
            logger.exception("Failed connection cleanup unconfirmed")
        finally:
            session.connection = None

    async def reconnect(self, session: Session, offer_sdp: str, generation: int) -> WebRTCAnswer:
        """Consume one fallback attempt; never retry an ambiguous billable POST."""
        manager = self.manager
        fallback = manager.fallback
        async with session.lock:
            if (
                session.adapter != "openai"
                or not session.preferences.azure_recovery
                or fallback is None
                or not fallback.capabilities.text_replay
            ):
                raise SessionError(501, "Fallback is not configured or cannot replay text")
            if session.fallback_used or generation != session.generation:
                raise SessionError(409, "Stale or duplicate fallback attempt")
            if session.state not in {"connected", "reconnecting"}:
                raise SessionError(409, "Session cannot reconnect")
            with (
                manager.metrics.operation("provider.failover"),
                manager.tracer.start_as_current_span(
                    "provider.failover",
                    record_exception=False,
                    context=session.turn.context if session.turn else None,
                ),
            ):
                already_reconnecting = session.state == "reconnecting"
                session.state = "reconnecting"
                session.fallback_used = True
                session.generation += 1
                if not manager.settings.intent_cancellation:
                    manager.delegator.cancel(session.delegation)
                manager.intent.pause(session.portfolio)
                session.portfolio.sequence = -1
                session.portfolio.awaiting_playback = False
                # Set "reconnecting" first: the watcher's finally must not re-enter close()
                # while this task holds session.lock, which would deadlock.
                if session.watcher is not None:
                    # A failed watcher is already closing its connection; let it finish.
                    if not already_reconnecting:
                        session.watcher.cancel()
                    await asyncio.gather(session.watcher, return_exceptions=True)
                # Transcript timestamps restart with the new transport; end the old turn first.
                if session.turn is not None:
                    session.turn.span.end()
                    session.turn = None
                try:
                    async with asyncio.timeout(manager.settings.connect_timeout_seconds):
                        if session.connection is not None:
                            session.previous_finalized = await session.connection.aclose()
                        session.connection = None
                        manager.seal_history(session, include_latest=True)
                        config = fallback.default_config(
                            manager.instructions_for(session),
                            tuple((e.speaker, e.text) for e in session.committed_history.entries),
                        )
                        session.connection = await fallback.connect(
                            config=config, offer_sdp=offer_sdp
                        )
                    session.state = "connected"
                    if session.costs is not None:
                        session.costs.connect("azure")
                    manager.start_watcher(session, "fallback-events")
                except BaseException as exc:
                    await manager.intent.close(session.portfolio)
                    manager.discard(session)
                    if isinstance(exc, TimeoutError):
                        raise SessionError(504, "Provider connection timed out") from exc
                    raise
                else:
                    return session.connection.answer
