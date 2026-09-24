"""Admission and lifecycle edge cases preserve cleanup and ownership."""

import asyncio
from pathlib import Path

import pytest
from conftest import BlockingProvider, FakeClock, PublicSettingsFactory, eventually
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import ProviderCapabilities, ProviderFailure
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import SessionError


async def test_sqlite_lease_released_on_connection_timeout(
    public_settings: PublicSettingsFactory, blocking_provider: BlockingProvider, tmp_path: Path
) -> None:
    manager = SessionManager(
        blocking_provider, public_settings(tmp_path, connect_timeout_seconds=0.01)
    )
    session = manager.create("alice")
    with pytest.raises(SessionError) as error:
        await manager.connect(session, "sdp")
    assert error.value.status == 504
    database = manager.admission.database
    assert database is not None
    assert database.execute("SELECT COUNT(*) FROM leases").fetchone() == (0,)
    assert database.execute("SELECT SUM(sessions) FROM reservations").fetchone() == (1,)
    await manager.aclose()


async def test_sqlite_release_failure_retains_lease_and_logs(
    public_settings: PublicSettingsFactory, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    manager = SessionManager(FakeProvider(), public_settings(tmp_path))
    session = manager.create("alice")
    database = manager.admission.database
    assert database is not None
    database.execute("PRAGMA query_only=ON")
    await manager.close(session)
    assert "Lease release unavailable" in caplog.text
    assert database.execute("SELECT COUNT(*) FROM leases").fetchone() == (1,)
    assert not manager.sessions
    await manager.aclose()


@pytest.mark.parametrize("close_first", [False, True])
async def test_concurrent_close_and_reconnect_release_all_connections(
    blocking_provider: BlockingProvider, close_first: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = FakeProvider()
    blocking_provider.capabilities = ProviderCapabilities(text_replay=True)
    manager = SessionManager(primary, Settings(), fallback=blocking_provider)
    session = manager.create()
    await manager.connect(session, "sdp")
    if close_first:
        entered, release = asyncio.Event(), asyncio.Event()
        old = primary.connections[0]
        original_close = old.aclose

        async def close() -> bool:
            entered.set()
            await release.wait()
            return await original_close()

        monkeypatch.setattr(old, "aclose", close)
        closing = asyncio.create_task(manager.close(session))
        await entered.wait()
        reconnecting = asyncio.create_task(manager.reconnect(session, "sdp", 0))
        release.set()
        await closing
        with pytest.raises(SessionError) as error:
            await reconnecting
        assert error.value.status == 409
    else:
        reconnecting = asyncio.create_task(manager.reconnect(session, "sdp", 0))
        await blocking_provider.started.wait()
        closing = asyncio.create_task(manager.close(session))
        blocking_provider.gate.set()
        await asyncio.gather(reconnecting, closing)
    assert all(c.closed for c in primary.connections + blocking_provider.connections)
    assert session.state == "closed" and not manager.sessions
    assert not session.lock.locked()
    await manager.aclose()


async def test_reconnecting_session_expires_without_browser_request(fake_clock: FakeClock) -> None:
    primary, fallback = FakeProvider(), FakeProvider()
    fallback.capabilities = ProviderCapabilities(text_replay=True)
    manager = SessionManager(
        primary, Settings(heartbeat_timeout_seconds=5), clock=fake_clock, fallback=fallback
    )
    session = manager.create()
    await manager.connect(session, "sdp")
    primary.connections[0].queue.put_nowait(ProviderFailure())
    await eventually(lambda: session.state == "reconnecting" and session.connection is None)
    fake_clock.advance(6)
    await manager.expire()
    assert session.state == "closed" and not manager.sessions
    assert not fallback.connections
    await manager.aclose()


@pytest.mark.parametrize("configured,status", [(False, 501), (True, 409)])
async def test_reconnect_rejects_missing_fallback_or_created_session(
    configured: bool, status: int
) -> None:
    fallback = FakeProvider()
    fallback.capabilities = ProviderCapabilities(text_replay=True)
    manager = SessionManager(FakeProvider(), Settings(), fallback=fallback if configured else None)
    session = manager.create()
    with pytest.raises(SessionError) as error:
        await manager.reconnect(session, "sdp", 0)
    assert error.value.status == status
    assert not fallback.connections
    await manager.aclose()
