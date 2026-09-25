"""Rejected provider commands do not consume fallback or cancel unrelated work."""

from collections.abc import Callable

import pytest
from conftest import BlockingWorker, eventually
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import (
    DelegationRequested,
    ProviderCommandError,
    ProviderEvent,
    ProviderFailure,
    Transcript,
)
from voice_delegate.providers.openai import normalize_event as live_event
from voice_delegate.providers.webrtc import normalize_event as realtime_event
from voice_delegate.session.manager import SessionManager


@pytest.mark.parametrize("normalize", [live_event, realtime_event])
async def test_command_error_preserves_session_and_running_worker(
    normalize: Callable[[str | bytes], ProviderEvent | None],
    blocking_worker: BlockingWorker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeProvider()
    manager = SessionManager(provider, Settings(), worker=blocking_worker, fallback=FakeProvider())
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    connection.queue.put_nowait(DelegationRequested("job", goal="calculate 2+2"))
    await blocking_worker.started.wait()
    event = normalize(
        '{"type":"error","error":{"type":"invalid_request_error","message":"private data"}}'
    )
    assert isinstance(event, ProviderCommandError)
    connection.queue.put_nowait(event)
    connection.queue.put_nowait(Transcript("assistant", "Still connected", 0, 0))
    await eventually(lambda: bool(session.history.entries))
    assert session.state == "connected"
    assert session.delegation.status == "running"
    assert not session.fallback_used
    assert not connection.closed
    assert "private data" not in caplog.text
    failure = normalize('{"type":"error","error":{"type":"server_error"}}')
    assert isinstance(failure, ProviderFailure)
    connection.queue.put_nowait(failure)
    await eventually(lambda: session.state == "reconnecting")
    await manager.aclose()
