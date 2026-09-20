# M1 verification

## Automated candidate checks

The candidate includes tests for admission capacity, session ownership, duplicate offers, heartbeat and absolute expiry, setup timeout, shutdown, provider errors, unavailable delegation, SDP request validation, body limits, wire mappings, queue overflow, and confirmed versus unconfirmed close.

The GitHub Actions workflow runs the same lint, types, tests, client build, and Python package build. It has been prepared locally; a remote workflow run requires a GitHub repository.

## Manual live gate — not yet executed

1. Use a project key with GPT-Live access via `.env`, following README quickstart.
2. Start the browser session. Confirm microphone capture, `session.started`, and audible output.
3. Speak in two supported languages and verify captions are independently updated.
4. Interrupt a spoken answer. Record whether playback and conversation follow the interruption naturally. Do not infer this from transcripts alone.
5. Request an external lookup. Confirm the model reports task execution unavailable and does not claim completion.
6. End the call. Confirm microphone indicator stops and the server reports confirmed finalization when `session.closed` is received.
7. Repeat with a closed tab, lost network, denied microphone permission, and a short configured absolute TTL. Check bounded cleanup and unconfirmed-close messaging.
8. Verify the browser never receives the project API key and the project contains only `.env.example` in Git.
9. Record test date, model, browser, observed setup/turn behavior, and any failed cases before creating `v0.1.0-m1`.

## Known verification boundaries

No real API call, microphone playback test, or hosted GitHub Actions execution has been performed for this candidate. Reflected sideband audio is discarded; it is not a playback measurement. Public documentation specifies the protocol, but account availability and runtime timing remain unverified until the live test.
