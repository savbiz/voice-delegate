Template: fill during live acceptance; status in [docs/roadmap.md](../roadmap.md).

# Live verification

This is an executable runbook, not a record of a successful run. No live calls were
made while preparing it. Obtain explicit authorization and a spend budget before
each paid run. Leave unmeasured cells blank. Never attach keys, invitation codes,
transcripts or private audio to the repository or PR.

## Preparation

- Record commit, date/time, primary/fallback/worker model versions, region, device,
  browser version, microphone/headphones, network and provider budget below.
- Use headphones, a foreground tab and a stable network. Disable server transcript
  recording for this run. Keep only numeric measurements and pass/fail observations.
- Follow [deployment commands and variables](../../deployment/README.md#live-acceptance).
  Enable `VOICE_AUDIO_TIMING=true`; keep it false outside the measurement run.
- Use the existing Vercel frontend and Railway backend, not a new deployment.
- Confirm `/healthz` succeeds and authenticated session creation accepts the intended
  invitation. Do not infer voice readiness from health alone.

## Smoke test

| Step | Action | Expected observation | Result / evidence |
|---|---|---|---|
| 1 | Start a GPT-Live call; allow microphone | Connected, audible greeting/response, no key in browser requests | |
| 2 | Ask a simple question, then repeat in another supported language | Audible answer and corresponding chat transcript | |
| 3 | Ask for a calculation, then a documentation lookup | Worker state changes; correct calculation and cited documentation result | |
| 4 | Request an unsupported external action | No false claim of completing that action | |
| 5 | Speak over an answer | Conversation responds naturally; record actual playback behavior | |
| 6 | Start delegated work, then speak again | With intent mode enabled, work continues; its result waits for observed silence | |
| 7 | Start another delegation, press Cancel task while it runs | Explicit cancellation and no later worker narration | |
| 8 | Press Stop | Microphone indicator clears; confirmed close or explicit unconfirmed-close message | |
| 9 | Repeat with denied microphone, tab close, network loss and short TTL | Bounded cleanup, useful errors, no orphaned active lease after expiry | |

## Audio measurement procedure

1. Open **Connection timings**. Check that audio measurement is enabled.
2. For setup samples, start a fresh call and ask the same short question immediately
   after connection. Record the offer-to-first-audio value. It includes provider
   setup and any wait before speaking; it is not provider-only generation latency.
3. For turn samples, ask one fixed short question at a time, then remain silent.
   Record **Speech end to audio** for each reply. Collect at least 20 eligible turns
   per environment; report the sample count and all exclusions, not just percentiles.
4. Repeat in a fresh session to identify warm/cold differences. Keep workloads,
   model, region and network constant. Do not mix providers in one aggregate.
5. Save numeric samples as a local JSON array in milliseconds. Compute nearest-rank
   percentiles with this command (replace the path with your local file):

```sh
python3 -c 'import json,math,sys; x=sorted(json.load(open(sys.argv[1]))); print({"n":len(x),"p50_ms":x[math.ceil(.5*len(x))-1],"p95_ms":x[math.ceil(.95*len(x))-1]})' /tmp/audio-samples.json
```

The browser observes WebRTC remote-stream energy while the audio element is playing,
unmuted and at nonzero volume. It samples every 20 ms. Turn origin is the last local
energy sample, with at least 300 ms silence before a fresh remote onset. This is
threshold-based, not semantic turn detection. Echo, noise and very quiet speech can
bias it. Muted/blocked playback, overlap, samples over 120 s and sampling gaps over
100 ms are excluded from turn measurement. AudioContext suspension prevents sampling.
Hardware output buffering and sound at the listener's ear are not measured. A physical
loopback recording is required for acoustic latency; record that separately if used.
Transcript gaps remain a separate diagnostic and must never be substituted.

## Azure recovery

Only run with authorized Azure credentials and a configured fallback. Follow
[Azure setup](../azure-setup.md). Verify offline recovery tests first.

1. Establish a primary GPT-Live call and make a short request with recognizable context.
2. In a controlled test environment, terminate only the backend's primary sideband
   connection (debugger/instrumented test harness). Record the monotonic failure time.
   Do not stop the backend or disable all networking: that would prevent fallback too.
3. Observe heartbeat `reconnecting`, one browser reconnect request, incremented
   transport generation and the Azure SDP answer. Verify prior context with a question.
4. Record failure-to-first-Azure-playback separately from offer-to-first-audio.
   The UI setup measurement starts at the fallback offer and excludes failure detection.
5. Repeat a failure after fallback: no second fallback attempt; clear terminal state.
6. Stop and verify both provider connections and the admission lease are released.

If selective fault injection is unavailable, mark recovery not verified. Do not add
an unauthenticated production fault-injection endpoint to complete this checklist.

## Hosted invitation acceptance

- Open https://voice-delegate.vercel.app/ in a clean browser profile.
- Check missing/invalid invitation rejection, valid invitation success, per-user
  concurrency and quota enforcement using a dedicated test invitation.
- Verify requests target the existing Railway host and CSP/CORS allow that origin.
- Run smoke steps 1–8; confirm Stop, then start another session within the allowance.
- Revoke the test invitation and confirm new sessions are rejected after restart.
- Inspect only safe status/error logs and aggregate metrics. Disable timing after testing.

## Environment and evidence

| Field | Value |
|---|---|
| Date/time and commit | |
| Model names/versions (primary, fallback, worker) | |
| Region | |
| Client device / audio devices | |
| Browser | |
| Network | |
| Authorized budget and observed usage | |
| Steps executed / excluded | |

| Measurement | n | p50 (ms) | p95 (ms) | Method / exclusions |
|---|---|---|---|---|
| Offer to first browser audio | | | | |
| Local speech end to browser audio | | | | |
| Acoustic end-to-end, if separately measured | | | | |
| Delegated task end-to-end | | | | |
| Failure to first fallback playback | | | | |

## Not verified

- Formal GPT-Live acceptance and representative latency distribution.
- Azure recovery with live audio.
- Hosted invitation end-to-end acceptance.
- Continued conversation without cancelling delegated work and silence-gated delivery
  (implemented behind `VOICE_INTENT_CANCELLATION`, live pending; see the [video script](../demo-video.md)).

## Optional intent-cancellation acceptance

Set `VOICE_INTENT_CANCELLATION=true` in the backend environment and restart. Leave
`VOICE_DECISIONS_CANCEL=false` for the initial voice test. Record the active flags alongside
the model names. Verify two tasks can remain running/pending, a third is rejected without
cancelling either, each result is introduced during observed silence, and Cancel targets only
the selected task. Check that backgrounding the browser holds delivery and eventually shows
expiry; a reconnect must preserve work and never reuse an old Realtime function-call identity.

Only after explicit approval for paid semantic testing, enable `VOICE_DECISIONS_CANCEL=true`.
Try an unambiguous cancellation and a continuation such as “while you work, explain something
else”. Record false cancellations and missed cancellations separately. A classifier failure
must leave the work running. Do not use the input-cost estimate as billing evidence.
