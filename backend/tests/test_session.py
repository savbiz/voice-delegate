"""Verify lifecycle, ownership, resource limits, and deterministic cleanup offline."""

import asyncio

import pytest
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeConnection, FakeProvider
from voice_delegate.providers.models import (
    DelegationRequested,
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
    with pytest.raises(TimeoutError):
        await manager.connect(session, "v=0\r\n")
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


async def test_m1_delegation_reports_unavailable_without_fake_success() -> None:
    provider = FakeProvider()
    manager = SessionManager(provider, Settings())
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    connection.queue.put_nowait(DelegationRequested("task-1"))
    await asyncio.sleep(0)
    assert connection.commands[0].delegation_id == "task-1"
    assert "No action was taken" in connection.commands[0].content
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
