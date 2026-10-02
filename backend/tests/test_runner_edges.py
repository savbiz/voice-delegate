"""Bound output and shutdown even when worker extensions or delivery misbehave."""

import asyncio

import pytest
from voice_delegate.delegation.contracts import DelegationInput
from voice_delegate.delegation.runner import DelegationRunner, DelegationState
from voice_delegate.limits.tokens import count_tokens, truncate
from voice_delegate.providers.fake import FakeConnection
from voice_delegate.providers.models import ProviderCommand, ProviderError
from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner
from voice_delegate_agent.reference import WorkerResult

from test_support import eventually


async def test_delivery_failure_is_reported() -> None:
    class BrokenConnection(FakeConnection):
        async def send(self, command: ProviderCommand) -> None:
            raise ProviderError("delivery failed")

    runner = DelegationRunner(LangGraphWorker(OfflinePlanner()))
    state = DelegationState()
    runner.start(
        state, "job", DelegationInput(goal="calculate 2+2"), BrokenConnection(), lambda: True
    )
    assert state.task is not None
    await state.task
    assert state.status == "delivery_failed" and not state.sources
    await runner.aclose()


async def test_shutdown_is_bounded_with_uncooperative_worker() -> None:
    started, release = asyncio.Event(), asyncio.Event()

    class StubbornWorker:
        async def delegate_task(self, goal: str, context: str) -> WorkerResult:
            started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue
            return WorkerResult("stale")

    runner = DelegationRunner(StubbornWorker())
    state, connection = DelegationState(), FakeConnection()
    runner.start(state, "job", DelegationInput(goal="wait"), connection, lambda: True)
    await started.wait()
    runner.cancel(state)
    assert state.task is not None
    await asyncio.gather(state.task, return_exceptions=True)
    try:
        async with asyncio.timeout(2):
            await runner.aclose()
        assert runner.work and not connection.commands
    finally:
        release.set()
        await eventually(lambda: not runner.work)
    assert not connection.commands


@pytest.mark.parametrize("budget", [0, -1])
def test_truncate_rejects_nonpositive_budget(budget: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        truncate("text", budget)


def test_truncate_caps_processing_of_oversized_text() -> None:
    result = truncate("word " * 25_000, 8, max_bytes=50)
    assert result.endswith("…")
    assert len(result.encode()) <= 50 and count_tokens(result) <= 8


@pytest.mark.parametrize("max_bytes", [0, 1, 2])
def test_truncate_returns_empty_when_marker_cannot_fit(max_bytes: int) -> None:
    assert truncate("long text", 1, max_bytes=max_bytes) == ""
