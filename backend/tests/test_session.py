"""Verify lifecycle, ownership, resource limits, and deterministic cleanup offline."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeConnection, FakeProvider
from voice_delegate.providers.models import (
    DelegationRequested,
    ProviderCapabilities,
    ProviderEvent,
    ProviderFailure,
    SessionConfig,
)
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import SessionError


async def test_capacity_ownership_and_cleanup() -> None:
    provider = FakeProvider()
    manager = SessionManager(provider, Settings(max_sessions=1))
    session = manager.create()
    with pytest.raises(SessionError) as forbidden:
        manager.get(session.id, "wrong")
    assert forbidden.value.status == 404
    with pytest.raises(SessionError) as capacity:
        manager.create()
    assert capacity.value.status == 429
    await manager.connect(session, "v=0\r\n")
    assert await manager.close(session)
    assert await manager.close(session)
    assert provider.connections[0].closed
    assert not manager.sessions
    manager.create()
    await manager.aclose()


async def test_duplicate_offers_create_only_one_upstream_call() -> None:
    provider = FakeProvider()
    manager = SessionManager(provider, Settings())
    session = manager.create()
    results = await asyncio.gather(
        manager.connect(session, "v=0\r\n"),
        manager.connect(session, "v=0\r\n"),
        return_exceptions=True,
    )
    assert len(provider.connections) == 1
    assert sum(isinstance(result, SessionError) for result in results) == 1
    await manager.aclose()


async def test_absolute_deadline_survives_heartbeats() -> None:
    now = [0.0]
    provider = FakeProvider()
    manager = SessionManager(
        provider, Settings(session_ttl_seconds=10, heartbeat_timeout_seconds=5), lambda: now[0]
    )
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    now[0] = 9
    manager.heartbeat(session)
    now[0] = 10
    await manager.expire()
    assert provider.connections[0].closed
    assert not manager.sessions


async def test_abandoned_unconnected_session_expires() -> None:
    now = [0.0]
    manager = SessionManager(FakeProvider(), Settings(heartbeat_timeout_seconds=5), lambda: now[0])
    manager.create()
    now[0] = 6
    await manager.expire()
    assert not manager.sessions


class SlowProvider(FakeProvider):
    """Hold setup until canceled by the application timeout."""

    async def connect(self, *, config: SessionConfig, offer_sdp: str) -> FakeConnection:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


async def test_setup_timeout_releases_capacity() -> None:
    manager = SessionManager(SlowProvider(), Settings(connect_timeout_seconds=0.01))
    session = manager.create()
    with pytest.raises(SessionError, match="Provider connection timed out") as error:
        await manager.connect(session, "v=0\r\n")
    assert error.value.status == 504
    assert isinstance(error.value.__cause__, TimeoutError)
    assert not manager.sessions
    assert session.state == "closed"


async def test_canceled_setup_releases_capacity() -> None:
    manager = SessionManager(SlowProvider(), Settings())
    session = manager.create()
    setup = asyncio.create_task(manager.connect(session, "v=0\r\n"))
    await asyncio.sleep(0)
    setup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await setup
    assert not manager.sessions
    assert session.state == "closed"


async def test_delegation_without_transcript_requests_clarification() -> None:
    provider = FakeProvider()
    manager = SessionManager(provider, Settings())
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    connection.queue.put_nowait(DelegationRequested("task-1"))
    await asyncio.sleep(0)
    assert session.delegation.task is not None
    await session.delegation.task
    assert connection.commands[0].delegation_id == "task-1"
    assert "repeat the task" in connection.commands[0].content
    await manager.aclose()


async def test_provider_error_closes_owned_resources() -> None:
    provider = FakeProvider()
    manager = SessionManager(provider, Settings())
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    provider.connections[0].queue.put_nowait(ProviderFailure())
    assert session.watcher is not None
    await session.watcher
    assert not manager.sessions
    assert provider.connections[0].closed


async def test_shutdown_rejects_new_sessions() -> None:
    manager = SessionManager(FakeProvider(), Settings())
    await manager.aclose()
    with pytest.raises(SessionError) as rejected:
        manager.create()
    assert rejected.value.status == 503


@pytest.mark.parametrize("shutdown", [False, True])
async def test_failed_close_does_not_stop_other_sessions(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, shutdown: bool
) -> None:
    now = [0.0]
    provider = FakeProvider()
    manager = SessionManager(provider, Settings(heartbeat_timeout_seconds=5), lambda: now[0])
    first, later = manager.create(), manager.create()
    await manager.connect(first, "v=0\r\n")
    await manager.connect(later, "v=0\r\n")

    async def fail() -> bool:
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(provider.connections[0], "aclose", fail)
    now[0] = 6
    if shutdown:
        await manager.aclose()
    else:
        await manager.expire()
        await manager.aclose()
    assert first.state == later.state == "closed"
    assert provider.connections[1].closed
    assert not manager.sessions
    assert "cleanup failed" in caplog.text


async def test_janitor_continues_after_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    manager = SessionManager(FakeProvider(), Settings())
    recovered = asyncio.Event()
    attempts = 0

    async def expire() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("unexpected expiry failure")
        recovered.set()

    monkeypatch.setattr(manager, "expire", expire)
    janitor = asyncio.create_task(manager.sweep())
    try:
        await asyncio.wait_for(recovered.wait(), 3)
    finally:
        janitor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await janitor
        await manager.aclose()
    assert "Session janitor failed" in caplog.text


@pytest.mark.parametrize("fallback", [False, True])
async def test_watcher_logs_unexpected_stream_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fallback: bool
) -> None:
    entered = asyncio.Event()
    fail = asyncio.Event()

    async def events(self: FakeConnection) -> AsyncIterator[ProviderEvent]:
        entered.set()
        await fail.wait()
        raise RuntimeError("event reader exploded")
        yield  # pragma: no cover

    provider = FakeProvider()
    provider.capabilities = ProviderCapabilities(text_replay=True)
    manager = SessionManager(FakeProvider(), Settings(), fallback=provider)
    session = manager.create()
    if fallback:
        await manager.connect(session, "v=0\r\n")
        monkeypatch.setattr(FakeConnection, "events", events)
        await manager.reconnect(session, "v=0\r\n", 0)
    else:
        monkeypatch.setattr(FakeConnection, "events", events)
        await manager.connect(session, "v=0\r\n")
    await entered.wait()
    fail.set()
    assert session.watcher is not None
    with pytest.raises(RuntimeError, match="event reader exploded"):
        await session.watcher
    await asyncio.sleep(0)
    assert "Session watcher failed" in caplog.text
    assert "event reader exploded" in caplog.text
    await manager.aclose()


async def test_watcher_failure_during_close_does_not_deadlock(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    closing = asyncio.Event()
    entered = asyncio.Event()

    async def events(self: FakeConnection) -> AsyncIterator[ProviderEvent]:
        entered.set()
        await closing.wait()
        raise RuntimeError("stream failed during close")
        yield  # pragma: no cover

    monkeypatch.setattr(FakeConnection, "events", events)
    provider = FakeProvider()
    manager = SessionManager(provider, Settings())
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    await entered.wait()
    watcher = session.watcher
    assert watcher is not None

    async def close_connection() -> bool:
        assert session.state == "closing"
        closing.set()
        await asyncio.wait({watcher})
        return True

    monkeypatch.setattr(provider.connections[0], "aclose", close_connection)
    assert await asyncio.wait_for(manager.close(session), 1)
    assert watcher.done()
    assert session.state == "closed" and not manager.sessions
    assert not session.lock.locked()
    assert "stream failed during close" in caplog.text
    await manager.aclose()
