"""Verify trace parenting, data minimization and metric export without sockets."""

import asyncio

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from voice_delegate.config import Settings
from voice_delegate.observability.metrics import Metrics, configure_metrics
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import (
    DelegationRequested,
    ProviderCapabilities,
    ProviderFailure,
    Transcript,
)
from voice_delegate.session.manager import SessionManager

from test_support import eventually


async def test_turn_parents_delegation_and_exports_no_private_text() -> None:
    spans = InMemorySpanExporter()
    tracing = TracerProvider()
    tracing.add_span_processor(SimpleSpanProcessor(spans))
    reader = InMemoryMetricReader()
    meters = MeterProvider(metric_readers=[reader])
    provider = FakeProvider()
    manager = SessionManager(
        provider, Settings(), tracer=tracing.get_tracer("test"), metrics=Metrics(meters)
    )
    session = manager.create()
    await manager.connect(session, "private-sdp")
    connection = provider.connections[0]
    connection.queue.put_nowait(Transcript("user", "private transcript", 0, 100))
    connection.queue.put_nowait(DelegationRequested("private-call"))
    await eventually(lambda: session.delegation.task is not None)
    assert session.delegation.task is not None
    await session.delegation.task
    connection.queue.put_nowait(Transcript("assistant", "private answer", 200, 300))
    await eventually(lambda: session.turn is not None and session.turn.replied)
    await manager.aclose()
    exported = spans.get_finished_spans()
    turn = next(span for span in exported if span.name == "conversation.turn")
    worker = next(span for span in exported if span.name == "delegate_task")
    assert worker.parent is not None and turn.context is not None
    assert worker.parent.span_id == turn.context.span_id
    assert "private" not in str([(s.attributes, s.events) for s in exported])
    data = reader.get_metrics_data()
    assert data is not None
    metric_names = {
        m.name for r in data.resource_metrics for s in r.scope_metrics for m in s.metrics
    }
    assert {"voice.operation.duration", "voice.turn.transcript_wait"} <= metric_names
    assert "private" not in str(data)
    tracing.shutdown()
    meters.shutdown()


def test_disabled_metrics_never_construct_an_exporter() -> None:
    assert configure_metrics(Settings()) is None
    assert configure_metrics(Settings(otel_enabled=True)) is None


def test_histograms_use_seconds_and_distinguish_cancellation() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    metrics = Metrics(provider)
    try:
        with pytest.raises(asyncio.CancelledError), metrics.operation("cancel"):
            raise asyncio.CancelledError
        with pytest.raises(ValueError), metrics.operation("fail"):
            raise ValueError("failure")
        metrics.turn_gap.record(0.2)
        data = reader.get_metrics_data()
        assert data is not None
        histograms = [m for r in data.resource_metrics for s in r.scope_metrics for m in s.metrics]
        for metric in histograms:
            for point in metric.data.data_points:
                assert isinstance(point, HistogramDataPoint)
                assert point.explicit_bounds == (
                    0.05,
                    0.1,
                    0.25,
                    0.5,
                    1,
                    2,
                    3,
                    5,
                    10,
                    20,
                    30,
                    60,
                    120,
                )
        operations = next(m for m in histograms if m.name == "voice.operation.duration")
        assert {p.attributes["outcome"] for p in operations.data.data_points if p.attributes} == {
            "cancelled",
            "error",
        }
    finally:
        provider.shutdown()


def test_enabled_tracing_has_a_batch_that_fits_its_bounded_queue() -> None:
    from voice_delegate.observability.tracing import configure_tracing

    provider = configure_tracing(Settings(otel_enabled=True, otel_endpoint=""))
    assert provider is not None
    provider.shutdown()


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        ("completed", "success"),
        ("failed", "error"),
        ("timeout", "error"),
        ("busy", "error"),
        ("delivery_failed", "error"),
        ("cancelled", "cancelled"),
    ],
)
async def test_worker_metrics_use_shared_outcomes(status: str, outcome: str) -> None:
    from voice_delegate.delegation.contracts import DelegationInput
    from voice_delegate.delegation.runner import DelegationRunner, DelegationState
    from voice_delegate.providers.fake import FakeConnection
    from voice_delegate.providers.models import ProviderCommand, ProviderError
    from voice_delegate_agent.reference import WorkerResult

    started = asyncio.Event()

    class Worker:
        async def delegate_task(self, goal: str, context: str) -> WorkerResult:
            started.set()
            if status in {"cancelled", "timeout"}:
                await asyncio.Event().wait()
            if status == "failed":
                raise ValueError("worker failure")
            return WorkerResult("4")

    class Connection(FakeConnection):
        async def send(self, command: ProviderCommand) -> None:
            if status == "delivery_failed":
                raise ProviderError("delivery failure")
            await super().send(command)

    reader = InMemoryMetricReader()
    meters = MeterProvider(metric_readers=[reader])
    runner = DelegationRunner(
        Worker(),
        metrics=Metrics(meters),
        capacity=0 if status == "busy" else 1,
        timeout=0.001 if status == "timeout" else 1,
    )
    state = DelegationState()
    runner.start(
        state, "request", DelegationInput(goal="calculate 2+2"), Connection(), lambda: True
    )
    assert state.task is not None
    if status == "cancelled":
        await started.wait()
        runner.cancel(state)
    await asyncio.gather(state.task, return_exceptions=True)
    assert state.status == status
    data = reader.get_metrics_data()
    assert data is not None
    points = [
        p
        for r in data.resource_metrics
        for s in r.scope_metrics
        for m in s.metrics
        if m.name == "voice.operation.duration"
        for p in m.data.data_points
    ]
    assert len(points) == 1
    assert points[0].attributes == {
        "operation": "delegate_task",
        "outcome": outcome,
        "status": status,
    }
    await runner.aclose()
    meters.shutdown()


@pytest.mark.parametrize("server_failure", [False, True])
async def test_reconnect_starts_a_new_turn_without_old_transport_wait(
    monkeypatch: pytest.MonkeyPatch, server_failure: bool
) -> None:
    spans = InMemorySpanExporter()
    tracing = TracerProvider()
    tracing.add_span_processor(SimpleSpanProcessor(spans))
    reader = InMemoryMetricReader()
    meters = MeterProvider(metric_readers=[reader])
    primary, fallback = FakeProvider(), FakeProvider()
    fallback.capabilities = ProviderCapabilities(text_replay=True)
    now = [10.0]
    monkeypatch.setattr("voice_delegate.observability.turns.monotonic", lambda: now[0])
    manager = SessionManager(
        primary,
        Settings(),
        fallback=fallback,
        tracer=tracing.get_tracer("test"),
        metrics=Metrics(meters),
    )
    try:
        session = manager.create()
        await manager.connect(session, "sdp")
        primary.connections[0].queue.put_nowait(Transcript("user", "first", 10000, 11000))
        await eventually(lambda: session.turn is not None)
        previous = session.turn
        assert previous is not None
        if server_failure:
            primary.connections[0].queue.put_nowait(ProviderFailure())
            await eventually(lambda: session.state == "reconnecting" and session.connection is None)
        await manager.reconnect(session, "sdp", 0)
        assert session.turn is None
        assert not previous.span.is_recording()
        now[0] = 100
        connection = fallback.connections[0]
        # An assistant event before the next user turn cannot complete the abandoned turn.
        connection.queue.put_nowait(Transcript("assistant", "reconnected", 0, 0))
        await eventually(connection.queue.empty)
        assert session.turn is None
        connection.queue.put_nowait(Transcript("user", "new request", 0, 0))
        await eventually(lambda: session.turn is not None)
        assert session.turn is not previous
        now[0] = 100.25
        connection.queue.put_nowait(Transcript("assistant", "new answer", 0, 0))
        await eventually(lambda: session.turn is not None and session.turn.replied)
        data = reader.get_metrics_data()
        assert data is not None
        points = [
            p
            for r in data.resource_metrics
            for s in r.scope_metrics
            for m in s.metrics
            if m.name == "voice.turn.transcript_wait"
            for p in m.data.data_points
        ]
        assert len(points) == 1
        point = points[0]
        assert isinstance(point, HistogramDataPoint)
        assert point.count == 1
        assert point.sum == pytest.approx(0.25)
    finally:
        await manager.aclose()
        tracing.shutdown()
        meters.shutdown()
    turns = [span for span in spans.get_finished_spans() if span.name == "conversation.turn"]
    assert len(turns) == 2
