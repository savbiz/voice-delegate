"""Verify trace parenting, data minimization and metric export without sockets."""

import asyncio

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from voice_delegate.config import Settings
from voice_delegate.observability.metrics import Metrics, configure_metrics
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import DelegationRequested, Transcript
from voice_delegate.session.manager import SessionManager


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
    await asyncio.sleep(0)
    assert session.delegation.task is not None
    await session.delegation.task
    connection.queue.put_nowait(Transcript("assistant", "private answer", 200, 300))
    await asyncio.sleep(0)
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


def test_enabled_tracing_has_a_batch_that_fits_its_bounded_queue() -> None:
    from voice_delegate.observability.tracing import configure_tracing

    provider = configure_tracing(Settings(otel_enabled=True, otel_endpoint=""))
    assert provider is not None
    provider.shutdown()
