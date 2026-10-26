"""App-owned metrics with finite labels and no transcript or identity attributes."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from time import monotonic

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from voice_delegate.config import Settings

SECOND_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 20, 30, 60, 120)


class Metrics:
    """Record operation duration and outcome; callers use fixed internal labels."""

    def __init__(self, provider: metrics.MeterProvider | None = None) -> None:
        meter = (provider or metrics.NoOpMeterProvider()).get_meter("voice_delegate")
        self.operations = meter.create_histogram(
            "voice.operation.duration",
            unit="s",
            description="Application operation duration",
            explicit_bucket_boundaries_advisory=SECOND_BUCKETS,
        )
        self.turn_gap = meter.create_histogram(
            "voice.turn.transcript_wait",
            unit="s",
            description="First assistant transcript arrival minus first user transcript arrival",
            explicit_bucket_boundaries_advisory=SECOND_BUCKETS,
        )
        self.audio_playback = meter.create_histogram(
            "voice.browser.audio_playback",
            unit="s",
            description="Client-reported time to first audio playback; not acoustic latency",
            explicit_bucket_boundaries_advisory=SECOND_BUCKETS,
        )
        self.task_cancellations = meter.create_counter("voice.task.cancellations", unit="1")
        self.deliveries = meter.create_counter("voice.task.deliveries", unit="1")
        self.decision_cost = meter.create_counter("voice.decision.estimated_cost", unit="USD")
        self.interruptions = meter.create_counter("voice.interruptions", unit="1")

    @contextmanager
    def operation(self, name: str) -> Iterator[None]:
        started = monotonic()
        outcome = "success"
        try:
            yield
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
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
        resource=Resource.create(
            {"service.name": "voice-delegate", "service.version": version("voice-delegate")}
        ),
        metric_readers=[reader],
    )
