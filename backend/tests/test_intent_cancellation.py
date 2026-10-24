"""Deterministic task, delivery and semantic cancellation races without provider calls."""

import asyncio

import pytest
from conftest import BlockingWorker, FakeClock
from pydantic import SecretStr
from voice_delegate.config import Settings
from voice_delegate.decisions import Decision, FakeDecider, Predicate
from voice_delegate.delegation.contracts import DelegationInput
from voice_delegate.delegation.intent import IntentRunner, Job, Portfolio
from voice_delegate.delegation.runner import DelegationRunner
from voice_delegate.providers.fake import FakeConnection, FakeProvider
from voice_delegate.providers.models import (
    Commentary,
    DelegationRequested,
    ProviderCapabilities,
    ProviderFailure,
    SpeechStarted,
    Transcript,
)
from voice_delegate.session.manager import SessionManager
from voice_delegate_agent.reference import WorkerResult

from test_support import eventually


async def test_speech_preserves_two_tasks_and_delivery_requires_fresh_silence(
    blocking_worker: BlockingWorker, fake_clock: FakeClock
) -> None:
    provider = FakeProvider()
    manager = SessionManager(
        provider, Settings(intent_cancellation=True), worker=blocking_worker, clock=fake_clock
    )
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    try:
        for identity in ("one", "two", "one", "three"):
            connection.queue.put_nowait(DelegationRequested(identity, goal="calculate 2+2"))
        await eventually(lambda: blocking_worker.calls == 2)
        assert session.portfolio.jobs["three"].status == "busy"
        assert session.portfolio.jobs["three"].finished == fake_clock()
        assert len(connection.commands) == 1
        connection.queue.put_nowait(SpeechStarted())
        connection.queue.put_nowait(Transcript("user", "Tell me something else", 100, 200))
        await eventually(lambda: bool(session.history.entries))
        assert session.portfolio.generation == 0
        assert not blocking_worker.cancelled.is_set()
        blocking_worker.gate.set()
        await eventually(lambda: all(j.status == "pending" for j in session.portfolio.active))
        # Neither missing activity nor stale silence permits delivery.
        await manager.intent.deliver(session.portfolio, connection, 0)
        assert len(connection.commands) == 1
        manager.intent.activity(session.portfolio, 0, speaking=False)
        fake_clock.advance(2)
        await manager.intent.deliver(session.portfolio, connection, 0)
        assert len(connection.commands) == 1
        manager.intent.activity(session.portfolio, 1, speaking=False)
        fake_clock.advance(0.7)
        manager.intent.activity(session.portfolio, 2, speaking=False)
        await manager.intent.deliver(session.portfolio, connection, 0)
        assert len(connection.commands) == 2
        assert connection.commands[-1].content == "About your request calculate 2+2: done"
        assert session.portfolio.jobs["one"].status == "completed"
        assert session.portfolio.jobs["two"].status == "pending"
        assert session.portfolio.jobs["one"].finished == fake_clock()
        assert [session.portfolio.jobs["two"].finished] == [None]
        manager.interrupt(session, task_id="two")
        assert session.portfolio.jobs["two"].status == "cancelled"
        assert session.portfolio.jobs["two"].finished == fake_clock()
        assert session.portfolio.jobs["one"].status == "completed"
        assert session.portfolio.generation == 1
    finally:
        await manager.aclose()


async def test_explicit_cancel_invalidates_uncooperative_result_only_for_selected_job(
    blocking_worker: BlockingWorker, fake_clock: FakeClock
) -> None:
    base = DelegationRunner(blocking_worker)
    runner = IntentRunner(base, Settings(intent_cancellation=True), fake_clock, None)
    state = Portfolio()
    try:
        for identity in ("a", "b"):
            runner.start(state, identity, DelegationInput(goal="calculate 1+1"), 0)
        await eventually(lambda: blocking_worker.calls == 2)
        runner.cancel(state, "explicit", "a")
        await blocking_worker.cancelled.wait()
        blocking_worker.gate.set()
        await eventually(lambda: state.jobs["b"].status == "pending")
        assert state.jobs["a"].status == "cancelled"
        assert state.jobs["a"].result is None
        fake_clock.advance(31)
        await runner.deliver(state, FakeConnection(), 0)
        assert state.jobs["b"].status == "expired"
        assert state.jobs["b"].finished == fake_clock()
        assert state.jobs["b"].result is None
        assert state.generation == 1
    finally:
        await runner.close(state)
        await base.aclose()


@pytest.mark.parametrize(
    ("probability", "fail", "cancelled"),
    [(0.84, False, False), (0.85, False, True), (1, True, False)],
)
async def test_semantic_threshold_and_error_fallback(
    blocking_worker: BlockingWorker,
    fake_clock: FakeClock,
    probability: float,
    fail: bool,
    cancelled: bool,
) -> None:
    base = DelegationRunner(blocking_worker)
    decider = FakeDecider(probability, fail=fail)
    settings = Settings(
        intent_cancellation=True, decisions_cancel=True, openai_api_key=SecretStr("offline-fixture")
    )
    runner = IntentRunner(base, settings, fake_clock, decider)
    state = Portfolio()
    try:
        runner.start(state, "a", DelegationInput(goal="calculate 1+1"), 0)
        await blocking_worker.started.wait()
        runner.transcript(state, "Cancel the calculation", "I am checking")
        assert state.decision is not None
        await state.decision
        assert (state.jobs["a"].status == "cancelled") is cancelled
        assert decider.calls == 1
    finally:
        await runner.close(state)
        await base.aclose()


async def test_disabled_decisions_and_call_budget(
    blocking_worker: BlockingWorker, fake_clock: FakeClock
) -> None:
    decider = FakeDecider(1)
    base = DelegationRunner(blocking_worker)
    settings = Settings(intent_cancellation=True)
    runner = IntentRunner(base, settings, fake_clock, decider)
    state = Portfolio()
    try:
        runner.start(state, "a", DelegationInput(goal="calculate 1+1"), 0)
        runner.transcript(state, "cancel", "")
        assert decider.calls == 0
        settings.decisions_cancel = True
        state.decision_calls = settings.decisions_max_calls
        runner.transcript(state, "cancel", "")
        assert state.decision is not None
        await state.decision
        assert decider.calls == 0
    finally:
        await runner.close(state)
        await base.aclose()


async def test_stale_decision_does_not_cancel_and_timeout_preserves_work(
    blocking_worker: BlockingWorker, fake_clock: FakeClock
) -> None:
    class SlowDecider(FakeDecider):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def decide(self, text: str, questions: tuple[Predicate, ...]) -> Decision:
            self.started.set()
            await self.release.wait()
            return Decision({"cancel_0": 0 if "Actually" in text else 1, "relevant_0": 0}, 100)

    decider = SlowDecider()
    base = DelegationRunner(blocking_worker)
    settings = Settings(
        intent_cancellation=True,
        decisions_cancel=True,
        decisions_timeout_seconds=0.05,
        openai_api_key=SecretStr("fixture"),
    )
    runner = IntentRunner(base, settings, fake_clock, decider)
    state = Portfolio()
    try:
        runner.start(state, "a", DelegationInput(goal="calculate 1+1"), 0)
        runner.transcript(state, "Cancel", "")
        await decider.started.wait()
        runner.transcript(state, "Actually keep working", "")
        decider.release.set()
        assert state.decision is not None
        await state.decision
        assert state.jobs["a"].status == "running"
        assert state.decision_cost == pytest.approx(0.00002)
        decider.release.clear()
        runner.transcript(state, "Cancel", "")
        await state.decision
        assert state.jobs["a"].status == "running"
    finally:
        await runner.close(state)
        await base.aclose()


async def test_reconnect_preserves_work_and_detaches_old_call_identity(
    blocking_worker: BlockingWorker, fake_clock: FakeClock
) -> None:
    provider, fallback = FakeProvider(), FakeProvider()
    fallback.capabilities = ProviderCapabilities(text_replay=True)
    manager = SessionManager(
        provider,
        Settings(intent_cancellation=True),
        clock=fake_clock,
        worker=blocking_worker,
        fallback=fallback,
    )
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    try:
        provider.connections[0].queue.put_nowait(DelegationRequested("a", goal="calculate 2+2"))
        await blocking_worker.started.wait()
        provider.connections[0].queue.put_nowait(ProviderFailure())
        await eventually(lambda: session.state == "reconnecting")
        await manager.reconnect(session, "v=0\r\n", 0)
        assert not blocking_worker.cancelled.is_set()
        blocking_worker.gate.set()
        await eventually(lambda: session.portfolio.jobs["a"].status == "pending")
        manager.intent.activity(session.portfolio, 0, speaking=False)
        fake_clock.advance(0.7)
        manager.intent.activity(session.portfolio, 1, speaking=False)
        await manager.intent.deliver(session.portfolio, fallback.connections[0], 1)
        assert fallback.connections[0].commands[0].detached
        assert not provider.connections[0].commands
    finally:
        await manager.aclose()


async def test_cancel_during_delivery_stops_send(
    blocking_worker: BlockingWorker, fake_clock: FakeClock
) -> None:
    class SlowConnection(FakeConnection):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()

        async def send(self, command: Commentary) -> None:
            self.started.set()
            await asyncio.Event().wait()
            self.commands.append(command)

    base = DelegationRunner(blocking_worker)
    runner = IntentRunner(base, Settings(intent_cancellation=True), fake_clock, None)
    state, connection = Portfolio(), SlowConnection()
    try:
        runner.start(state, "a", DelegationInput(goal="calculate 1+1"), 0)
        blocking_worker.gate.set()
        await eventually(lambda: state.jobs["a"].status == "pending")
        runner.activity(state, 0, speaking=False)
        fake_clock.advance(0.7)
        delivery = asyncio.create_task(runner.deliver(state, connection, 0))
        await connection.started.wait()
        runner.cancel(state, "explicit", "a")
        await delivery
        assert not connection.commands
        assert state.jobs["a"].status == "cancelled"
    finally:
        await runner.close(state)
        await base.aclose()


async def test_request_limit_does_not_cancel_and_stale_activity_cannot_release(
    blocking_worker: BlockingWorker, fake_clock: FakeClock
) -> None:
    base = DelegationRunner(blocking_worker, request_limit=1)
    runner = IntentRunner(base, Settings(intent_cancellation=True), fake_clock, None)
    state = Portfolio()
    try:
        request = DelegationInput(goal="calculate 1+1")
        assert runner.start(state, "one", request, 0) is None
        assert runner.start(state, "one", request, 0) is None
        assert runner.start(state, "two", request, 0) == Commentary(
            "two", "Delegation limit reached"
        )
        await blocking_worker.started.wait()
        assert blocking_worker.calls == 1 and state.generation == 0
        runner.activity(state, 4, speaking=True)
        runner.activity(state, 3, speaking=False)
        assert state.quiet_since == float("inf")
        state.awaiting_playback = True
        runner.activity(state, 5, speaking=True, assistant_speaking=True)
        assert not state.awaiting_playback
    finally:
        await runner.close(state)
        await base.aclose()


async def test_intent_metrics_have_finite_labels_and_no_content(
    blocking_worker: BlockingWorker, fake_clock: FakeClock
) -> None:
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from voice_delegate.observability.metrics import Metrics

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    base = DelegationRunner(blocking_worker, metrics=Metrics(provider))
    runner = IntentRunner(base, Settings(intent_cancellation=True), fake_clock, None)
    state = Portfolio()
    try:
        runner.start(state, "private-id", DelegationInput(goal="private-goal"), 0)
        await blocking_worker.started.wait()
        runner.cancel(state, "explicit")
        await runner.close(state)
        data = reader.get_metrics_data()
        assert data is not None
        metrics = data.resource_metrics[0].scope_metrics[0].metrics
        cancelled = next(m for m in metrics if m.name == "voice.task.cancellations")
        assert cancelled.data.data_points[0].attributes == {"reason": "explicit"}
        assert "private" not in str(data)
    finally:
        await runner.close(state)
        await base.aclose()
        provider.shutdown()


async def test_two_results_require_separate_playback_and_silence_windows(
    blocking_worker: BlockingWorker, fake_clock: FakeClock
) -> None:
    base = DelegationRunner(blocking_worker)
    runner = IntentRunner(base, Settings(intent_cancellation=True), fake_clock, None)
    state, connection = Portfolio(), FakeConnection()
    try:
        for identity in ("one", "two"):
            runner.start(state, identity, DelegationInput(goal="calculate 1+1"), 0)
        blocking_worker.gate.set()
        await eventually(lambda: all(j.status == "pending" for j in state.active))
        runner.activity(state, 0, speaking=False)
        fake_clock.advance(0.7)
        await runner.deliver(state, connection, 0)
        assert len(connection.commands) == 1
        runner.activity(state, 1, speaking=False)
        fake_clock.advance(0.7)
        await runner.deliver(state, connection, 0)
        assert len(connection.commands) == 1
        runner.activity(state, 2, speaking=True, assistant_speaking=True)
        runner.activity(state, 3, speaking=False)
        fake_clock.advance(0.7)
        await runner.deliver(state, connection, 0)
        assert [c.delegation_id for c in connection.commands] == ["one", "two"]
        assert state.status == "completed"
    finally:
        await runner.close(state)
        await base.aclose()


@pytest.mark.parametrize("send_fails", [False, True])
async def test_failed_results_and_send_failures_freeze_duration(
    blocking_worker: BlockingWorker, fake_clock: FakeClock, send_fails: bool
) -> None:
    class DeliveryConnection(FakeConnection):
        async def send(self, command: Commentary) -> None:
            if send_fails:
                raise RuntimeError("fixture delivery failure")
            self.commands.append(command)

    base = DelegationRunner(blocking_worker)
    runner = IntentRunner(base, Settings(intent_cancellation=True), fake_clock, None)
    state = Portfolio()
    job = Job(
        "task",
        "Calculate",
        fake_clock(),
        0,
        status="pending",
        ready=fake_clock(),
        result=WorkerResult("Task failed", status="failed"),
    )
    state.jobs[job.id] = job
    try:
        runner.activity(state, 0, speaking=False)
        fake_clock.advance(0.7)
        await runner.deliver(state, DeliveryConnection(), 0)
        assert job.status == ("delivery_failed" if send_fails else "failed")
        finished = fake_clock()
        assert job.finished == finished
        fake_clock.advance(10)
        await runner.deliver(state, None, 0)
        assert job.finished == finished
    finally:
        await runner.close(state)
        await base.aclose()
