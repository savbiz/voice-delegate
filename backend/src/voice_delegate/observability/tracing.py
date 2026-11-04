"""Optional lifecycle tracing with no transcript, SDP, or credential attributes."""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from voice_delegate.config import Settings

from .otlp import standard_endpoint


def configure_tracing(settings: Settings) -> TracerProvider | None:
    """Create an app-owned exporter, or remain completely offline when disabled."""
    if not settings.otel_enabled:
        return None
    provider = TracerProvider(resource=Resource.create({"service.name": "voice-delegate"}))
    exporter: OTLPSpanExporter | ConsoleSpanExporter
    if settings.otel_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, timeout=3)
    elif standard_endpoint():
        exporter = OTLPSpanExporter(timeout=3)
    else:
        exporter = ConsoleSpanExporter()
    provider.add_span_processor(
        BatchSpanProcessor(exporter, max_queue_size=256, max_export_batch_size=256)
    )
    return provider


def get_tracer(provider: TracerProvider | None) -> trace.Tracer:
    """Keep app factories isolated without changing the global OTel provider."""
    return (provider or trace.NoOpTracerProvider()).get_tracer("voice_delegate")
