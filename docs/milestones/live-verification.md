Template: fill during live acceptance; status in [docs/roadmap.md](../roadmap.md).

# Live verification

Fill this record while executing the checklist below.
Leave unmeasured fields blank and record gaps under “Not verified”.

## Live smoke-test checklist

1. Use a project key with GPT-Live access via `.env`, following README quickstart.
2. Start the browser session. Confirm microphone capture, `session.started` (Live) or `session.created` (Realtime), and audible output.
3. Speak in two supported languages and verify captions are independently updated.
4. Interrupt a spoken answer. Record whether playback and conversation follow the interruption naturally. Do not infer this from transcripts alone.
5. Request a calculation and documentation search; confirm delegation returns a cited result. Request an unsupported external action and confirm the model does not claim to have performed it.
6. End the call. Confirm microphone indicator stops and the server reports confirmed finalization when `session.closed` is received.
7. Repeat with a closed tab, lost network, denied microphone permission, and a short configured absolute TTL. Check bounded cleanup and unconfirmed-close messaging.
8. Verify the browser never receives the project API key and the project contains only `.env.example` in Git.
9. Record test date, model, browser, observed setup/turn behavior, and any failed cases before claiming live acceptance.

## Test environment

| Field | Value |
|---|---|
| Date | |
| Model names (primary, fallback, worker) | |
| Region | |
| Client device | |
| Browser | |
| Network | |

## Steps executed

| Step | Observed result | Evidence |
|---|---|---|
| | | |

## Measured latency

| Measurement | p50 (ms) | p95 (ms) |
|---|---|---|
| Provider time-to-first-byte | | |
| Delegated task end-to-end | | |
| Failover time | | |

## Not verified

- 
