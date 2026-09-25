# Backend observability

Set `GF_SECURITY_ADMIN_PASSWORD` to a private admin password, then start the local stack with `docker compose -f observability/compose.yaml up -d`.
Set these backend variables and restart the API:

```dotenv
VOICE_OTEL_ENABLED=true
VOICE_OTEL_ENDPOINT=http://localhost:4318/v1/traces
VOICE_OTEL_METRICS_ENDPOINT=http://localhost:4318/v1/metrics
```

Grafana: http://localhost:3000 (anonymous viewer); Prometheus: http://localhost:9090.
Provisioning loads the dashboard automatically. Traces go to collector logs; inspect with
`docker compose -f observability/compose.yaml logs collector`. No trace-storage backend is
included. Stop with `docker compose -f observability/compose.yaml down`.
The example binds only loopback; data is ephemeral and metrics retention is 24 hours.
Images are pinned reference versions, not a claim to latest security updates.

`conversation.turn` spans use transcript heuristics: a new user segment after a reply or
an 800 ms transcript gap starts a turn. Provider transcript spans, delegation spans and
failover spans share that parent. Turns end at the next turn, close or failed fallback.
An idle turn can remain open until session expiry. No transcript, session IDs, SDP,
credentials, provider request bodies or tool results are exported.

Metrics use finite operation/outcome labels:

Operation outcomes are `success`, `error`, and `cancelled`. The names below are
post-collector Prometheus names, rather than the dotted OpenTelemetry instrument names.
Both duration histograms use explicit second boundaries:
`0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 20, 30, 60, 120`.

- `voice_operation_duration_seconds`: provider setup, fallback and worker duration.
- `voice_turn_transcript_wait_seconds`: first assistant transcript arrival minus first
  user transcript arrival. This includes speech and transcription time; it is not audio TTFB.
- `voice_interruptions_total`: worker tasks canceled while pending, including close/fallback.

The browser's transcript gap remains a separate estimate based on provider timestamps,
or a labelled client-side estimate when those timestamps are absent.
Signaling duration, transcript arrival and audio playback are different measures. Audio
TTFB, playback onset and end-to-end acoustic latency require a live measurement harness;
this project does not export invented values for them. Fake runs measure orchestration only.

OTel is disabled by default. Tests inject in-memory exporters and do not use network services.
Metrics export additionally requires `VOICE_OTEL_METRICS_ENDPOINT`; there is no public
application metrics endpoint. Collector buffers and container memory are bounded.
