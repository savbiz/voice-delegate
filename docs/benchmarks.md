# Reproducible voice benchmarks

## Verification status

Prepared 2026-11-01. No paid voice benchmark has been run for this comparison.
Offline scoring tests use deliberately imperfect scripted observations. Browser tests
send a generated tone through a local WebRTC peer pair and observe received audio.
Neither measures provider quality, voice recognition or physical speaker latency.

| Provider | Transport | Model/version | Live samples | First audio p50/p95 | Turn p50/p95 | Delegation accuracy |
| --- | --- | --- | --- | --- | --- | --- |
| GPT-Live | Direct WebRTC | Pending: record configured model | 0 | Pending | Pending | Pending |
| OpenAI Realtime | Direct WebRTC | Pending: record configured model | 0 | Pending | Pending | Pending |
| Azure Live | Direct WebRTC | Pending: record deployment and underlying model version | 0 | Pending | Pending | Pending |
| ElevenLabs | Not implemented | Pending transport decision | 0 | Unsupported | Unsupported | Unsupported |

Do not replace Pending with scripted numbers. Earlier exploratory conversations are not
the fixed-input benchmark. A model alias can change server-side; record its resolved
version from the provider console alongside the operator-declared model in the artifact.

## Fixed cases and method

[voice-v1.json](../evals/data/voice-v1.json) contains 30 independent English utterances:
ten require delegation explicitly, ten require a direct response, ten are ambiguous.
Use a fresh session for each utterance so previous context cannot change the label.
Ambiguous cases report delegation frequency, with no invented right/wrong score.
For definite labels, divide correct observations by **all attempts**, including failures.
Missing delegation evidence is unknown, never automatically a direct answer.

The browser probe uses one `AudioContext` clock for scheduled input and received-audio
energy. It sends a prerecorded WAV through a `MediaStreamAudioDestinationNode` into
WebRTC, plays the received track, and samples its RMS energy every 20 ms (threshold 0.02).
It does not request microphone access. Silence is one second below that threshold.

* `setup_ms`: offer construction to first observed remote playback energy. This includes
  connection setup and the input utterance; compare only identical recordings.
* `first_audio_ms`: labelled end of input speech to first remote playback energy. This
  is the end-to-end response-onset measure, not a transcript gap or provider TTFB.
* `turn_ms`: labelled end of input speech to the last energy sample of the observed
  response burst, followed by one second of silence. The silence confirmation is excluded.
  It is a burst-completion heuristic: long pauses or a later worker delivery can produce
  another burst. It does not prove completion of every task or playback of every result.

Overlapping replies, timeouts, connection errors and unconfirmed closes are censored from
latency percentiles and counted separately. The report includes sample count, p50 and p95
using linear interpolation; a single trial is exploratory, not a confidence interval.
Headless Chromium observes the playback pipeline, not sound at a physical speaker.
Timer scheduling, codecs, network, hardware and VAD affect results. Repeat the same input
hashes and browser version on the same host/network, then record those conditions in the
published run notes. Do not compare a hosted run with a local run as a provider-only change.

Delegation is observed via GPT-Live `session.delegation.created`, Realtime/Azure
`response.function_call_arguments.done` for `delegate_task`, and the owned heartbeat task
state. Payloads and transcripts are discarded. A response can contain narration while a
worker is still running; this benchmark measures the voice model's delegation decision,
not the worker planner's tool-selection accuracy. See the separate
[planner comparison](../evals/README.md#planner-comparison).

## Offline commands: no provider or key

From the repository root:

```sh
uv run python -m evals.voice_benchmark --output .local/benchmarks/scripted.json
```

For a real browser-to-browser media loopback, from `frontend/`:

```sh
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
pnpm benchmark:voice --output ../.local/benchmarks/loopback.json
```

Then from the repository root:

```sh
uv run python -m evals.voice_benchmark \
  --capture .local/benchmarks/loopback.json \
  --output .local/benchmarks/loopback-report.json
```

The loopback has 30 tone trials, not 30 spoken questions. Its purpose is to exercise
media capture, measurement and cleanup without a provider. The offline browser disables
ICE mDNS hiding to permit local candidate resolution; live runs retain browser defaults.
Reports distinguish dirty working trees and reject incomplete runs when scoring.

## Recording the input set

Record the exact utterances from the versioned dataset yourself, or use recordings you
have permission to redistribute. Do not add provider-generated speech or personal
conversations to the repository. Keep the WAV files in ignored `.local/benchmarks/clips/`.
Use PCM WAV, at most 10 seconds and 1 MB per file, with minimal trailing silence. Mark
the end of actual speech manually; the boundary is not necessarily the end of the file.
Do not trim differently between providers.

Create `manifest.json` in that folder, containing all 30 IDs with this shape:

```json
{
  "delegate-01": {
    "file": "delegate-01.wav",
    "sha256": "replace with the 64-character SHA-256 of the file",
    "speech_end_ms": 3200
  }
}
```

Generate each hash with `shasum -a 256 .local/benchmarks/clips/delegate-01.wav`.
The runner verifies every hash, size and path before opening a paid session. Browser
decoding also verifies duration and speech boundary; invalid audio produces a failed
observation. Record sample rate, recording method and boundary uncertainty in run notes.

## Live commands: explicit authorization required

Do not run these commands until the maintainer authorizes this paid comparison. They
use the existing API; they do not provision or modify Railway or Vercel. Keep real provider
keys on the backend. Put only a dedicated benchmark invitation in
`VOICE_BENCHMARK_INVITATION` in the runner's environment, never a provider key.

Use a clean committed checkout. Start a **dedicated local** backend with the existing
environment credentials, selecting one provider per run. Example for GPT-Live:

```sh
VOICE_ADAPTER=openai VOICE_WORKER_MODE=offline \
VOICE_PUBLIC_DEMO=false VOICE_ENVIRONMENT=development \
VOICE_ALLOWED_ORIGINS='["http://127.0.0.1:4175"]' \
uv run uvicorn voice_delegate.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Keep existing access controls. If public-demo admission is deliberately enabled on a
dedicated benchmark instance, use its named invitation and sufficient configured daily
quota (30 sessions for one trial). Do not relax hosted user quotas to run the benchmark.
`VOICE_INTENT_CANCELLATION` and `VOICE_DECISIONS_CANCEL` must be explicitly recorded in
run notes. Use the offline worker and leave Decisions off for the baseline so these calls
measure voice-provider behavior rather than additional paid planner/classifier work.

From `frontend/`, after authorization:

```sh
VOICE_BENCHMARK_LIVE=true pnpm benchmark:voice --live --allow-paid \
  --provider live --model gpt-live-1 --max-sessions 30 \
  --api http://127.0.0.1:8000 \
  --recordings ../.local/benchmarks/clips \
  --output ../.local/benchmarks/live.json
```

The provider/model arguments are labels, not client overrides. They **must match** the
backend configuration: use `VOICE_ADAPTER=realtime` and `VOICE_REALTIME_MODEL` for
OpenAI Realtime, or `VOICE_ADAPTER=azure`, `VOICE_AZURE_ENDPOINT`,
`VOICE_AZURE_DEPLOYMENT` and `VOICE_AZURE_API_KEY` for Azure. Restart the dedicated backend
between providers. Azure requires valid existing endpoint credentials; ElevenLabs is
rejected until its adapter exists. Never enable fallback during a provider comparison.

Run the Python summarizer on each complete capture as shown above. The exact session
budget is mandatory: 30 for one trial, 60 with `--trials 2`. There are no retries. Each
API operation has a deadline, ICE setup is bounded, input clips are bounded and response
observation is limited to 15 seconds after the input. The runner closes each owned session
before starting the next. Failures remain observations; partial captures are retained for
diagnosis but cannot become a complete benchmark summary. Session expiry is the final
backstop if the runner is forcibly killed. A session cap is not a dollar billing cap.

## Trace evidence from Grafana

The checked-in stack provisions **Prometheus only** in Grafana; the collector's trace
pipeline prints basic diagnostic output and does not retain a queryable trace archive.
No exported live trace is currently claimed. Do not treat dashboard JSON or the browser
capture as a distributed trace. This PR does not add a new hosted service or dependency.

If an operator already has a Tempo data source receiving this app's opted-in OTel spans,
find the trace in Grafana Explore and record its trace ID and data source UID. Export a
bounded timing-only projection from the repository root:

```sh
uv run python -m evals.export_grafana \
  --origin http://localhost:3000 --datasource tempo \
  --trace-id 0123456789abcdef0123456789abcdef \
  --output .local/benchmarks/trace.json
```

Set `GRAFANA_TOKEN` in the environment if read access requires authentication. The request
has a five-second total network deadline, a 2 MB cap and no redirects. Environment proxies
and environment TLS overrides are ignored so a loopback bearer token stays on the direct
connection. Export keeps known operation names
and start/end times; attributes, events, resource data and arbitrary span names are
discarded. Errors leave no successful artifact and never print the response body.
Archive the exported projection beside the capture and run notes. Grafana/Tempo access
and this live export remain pending; offline mock tests verify limits and redaction.

Sources: [OpenAI WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc),
[server-side controls](https://developers.openai.com/api/docs/guides/voice-server-controls),
[Grafana data source proxy API](https://grafana.com/docs/grafana/latest/developer-resources/api-reference/http-api/api-legacy/data_source/),
[Tempo trace query API](https://grafana.com/docs/tempo/latest/api_docs/).
