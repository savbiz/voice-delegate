"""App-owned metrics with finite labels and no transcript or identity attributes."""

from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from voice_delegate.config import Settings


class Metrics:
    """Record operation duration and outcome; callers use fixed internal labels."""

    def __init__(self, provider: metrics.MeterProvider | None = None) -> None:
        meter = (provider or metrics.NoOpMeterProvider()).get_meter("voice_delegate")
        self.operations = meter.create_histogram(
            "voice.operation.duration", unit="s", description="Application operation duration"
        )
        self.turn_gap = meter.create_histogram(
            "voice.turn.transcript_wait",
            unit="s",
            description="First assistant transcript arrival minus first user transcript arrival",
        )
        self.interruptions = meter.create_counter("voice.interruptions", unit="1")

    @contextmanager
    def operation(self, name: str) -> Iterator[None]:
        started = monotonic()
        outcome = "success"
        try:
            yield
        except BaseException:
            outcome = "error"
            raise
        finally:
            self.operations.record(monotonic() - started, {"operation": name, "outcome": outcome})


def configure_metrics(settings: Settings) -> MeterProvider | None:
    if not settings.otel_enabled or not settings.otel_metrics_endpoint:
        return None
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=settings.otel_metrics_endpoint, timeout=3),
        export_interval_millis=10000,
        export_timeout_millis=4000,
    )
    return MeterProvider(
        resource=Resource.create({"service.name": "voice-delegate"}), metric_readers=[reader]
    )
