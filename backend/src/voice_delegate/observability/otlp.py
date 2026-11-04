"""Standard OpenTelemetry exporter variables, as hosted backends hand them out.

Hosted services such as Grafana Cloud give three variables: `OTEL_EXPORTER_OTLP_PROTOCOL`,
`OTEL_EXPORTER_OTLP_ENDPOINT` (a base URL) and `OTEL_EXPORTER_OTLP_HEADERS` (authentication).
The OTLP exporters read them by themselves and append `/v1/traces` and `/v1/metrics`.
Explicit `VOICE_OTEL_*` endpoints take precedence. The variables must be process
environment variables; a `.env` file does not reach the exporters.
"""

import os


def standard_endpoint() -> bool:
    """Whether the process environment names a standard OTLP base endpoint."""
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())
