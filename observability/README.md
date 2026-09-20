# OpenTelemetry

M1 includes optional `provider.connect` spans for signaling setup, with no SDP, transcript, session key or credential attributes. Export is disabled by default, including offline tests. Turn-level traces, provider/delegation metrics, Prometheus, and Grafana belong to M4; setup duration is not turn latency.

Set `VOICE_OTEL_ENABLED=true` to export traces to the console. For the optional local collector:

```bash
docker compose -f observability/compose.yaml up
```

Then set `VOICE_OTEL_ENDPOINT=http://localhost:4318/v1/traces` in the backend environment and restart it. The collector prints received spans. Its port binds only to localhost; protect an external collector with transport authentication before remote use. Batch export uses a bounded queue and shuts down with the app.

Reference: [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/).
