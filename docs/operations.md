# Demo operations runbook

This runbook covers one backend process with a durable local volume, or the bundled same-host topology. It does not claim multi-region availability. See [production scope](production.md) and the generated [settings reference](configuration.md).

## Disable new sessions

Set `VOICE_DEMO_ENABLED=false` on the backend and restart/redeploy every API instance. The setting is read at startup; changing the dashboard value alone does not update an existing process. New session creation returns 503. This is an admission switch, not a provider-side spend cutoff. Restart closes local sessions where possible; a crashed or unreachable provider connection can remain unconfirmed. Reference search and authenticated heartbeat/close do not depend on this switch. Re-enable only after the incident is understood.

## Rotate or revoke an invitation

Edit `VOICE_INVITE_TOKENS`, a JSON map of stable pseudonymous names to unique random tokens of at least 32 characters. Generate a replacement locally with `uv run python -c 'import secrets; print(secrets.token_urlsafe(32))'`. Keep the name unchanged when rotating so its hashed quota identity and reservations remain associated. Remove the name to revoke it. Apply the same mapping to all API instances and restart them. Distribute tokens privately. Never put tokens in URLs, screenshots, issue reports or frontend environment variables. `VOICE_ACCESS_TOKEN` is only for private testing, not the public-demo profile.

## Quotas and cost controls

- `VOICE_DAILY_SESSIONS_PER_USER` limits sessions reserved per principal per UTC day.
- `VOICE_CONCURRENT_SESSIONS_PER_USER` limits active leases per principal.
- `VOICE_MAX_SESSIONS` caps local API sessions and, with shared SQLite, global active leases.
- `VOICE_DAILY_VOICE_SECONDS_PER_USER` and `VOICE_DAILY_VOICE_SECONDS_GLOBAL` cap reserved voice seconds per UTC day. Each admitted session reserves `ceil(session_ttl_seconds + 1)`, doubled when fallback is enabled. Early close and failed connect do not refund the reservation.
- `VOICE_SESSION_TTL_SECONDS` bounds a conversation's lifetime. Heartbeat expiry reclaims abandoned sessions; neither heartbeat nor fallback extends the absolute TTL.
- `VOICE_MAX_DELEGATIONS_PER_SESSION` caps accepted distinct worker requests. An over-limit request does not cancel already-running work.
- Worker step, duration, result-size and concurrency limits cap application-owned work; they are not a dollar-accurate billing meter.

Use project-scoped provider keys. Configure provider budget alerts and available hard spending controls; verify whether the selected provider/account treats a budget as a warning or actually rejects additional use. Monitor billed usage separately from local reserved seconds. Disable new sessions and revoke/disable a provider key if uncontrolled provider usage continues. Never assume a local timeout proves upstream billing stopped.

## Inspect persistent SQLite state

The hosted volume mounts at `/app/.local`; quota and feedback paths must point inside it and be writable by the process. Railway's platform-managed volume ownership may require the documented `RAILWAY_RUN_UID=0` exception; see [deployment](../deployment/README.md). Do not delete or replace the volume to fix an application startup error.

From an administrative shell where the `sqlite3` CLI is available, use read-only queries:

```bash
sqlite3 -readonly /app/.local/quotas.sqlite3 'SELECT day, SUM(sessions), SUM(seconds) FROM reservations GROUP BY day;'
sqlite3 -readonly /app/.local/quotas.sqlite3 'SELECT COUNT(*), MIN(expires), MAX(expires) FROM leases;'
sqlite3 -readonly /app/.local/feedback.sqlite3 'SELECT category, state, COUNT(*) FROM feedback GROUP BY category, state;'
```

Quota principals are hashes, not invitation tokens. Leases expire even if release fails. Reservations roll over by UTC day. Feedback has no free-text field, retains reports for seven days, allows five per principal per rolling 24 hours, and caps storage at 10,000 records. Treat backups as sensitive operational data. Use SQLite's backup mechanism or a quiesced consistent volume snapshot; copying a live WAL database file alone is not a safe backup.

## Rollback while retaining data

Record the deployed commit/image and settings before rollout. Disable new sessions and drain/close conversations where possible. Redeploy the previously verified commit/image while retaining the same volume, database paths, invitation names and instance IDs. Check schema compatibility before rollback; retain a consistent backup and a tested restore procedure. Do not blindly restore an older quota database, which could erase reservations and permit extra usage. After restart, verify `/healthz`, `/api/config`, an authenticated documentation search and admission behavior. Only then re-enable new conversations. The [live-verification template](milestones/live-verification.md) records voice acceptance separately.

## Diagnose an unconfirmed close

`finalized=false` means local cleanup completed without confirmation for one or more provider connections. Inspect redacted provider/cleanup logs and the provider's usage dashboard. Do not retry an ambiguous session-creation POST: it may create a second billable call. Escalate persistent usage through provider controls. A browser showing “ended” proves local media release, not provider-side finalization.

## Monitor and escalate

Check backend health, worker busy/timeouts, provider error/cancelled outcomes, lease counts and provider billed usage. Use [observability](../observability/README.md) for optional local dashboards; hosted alerting and trace retention are operator responsibilities. For a security issue use the [private reporting channel](../SECURITY.md), not a public transcript or log dump.

## Temporary API documentation

Set `VOICE_API_DOCS=true` temporarily to expose Swagger; default off in production. Restart the backend to apply it. This also exposes ReDoc and the OpenAPI schema without invitation authentication, subject to host and rate middleware. Restore `false` and restart after inspection. Development exposes these routes by default.

## Investigating interrupted audio locally

For a local Live test, set `VOICE_VOICE_PROVIDER=live` and `VOICE_MODEL=gpt-live-1`
in the untracked root `.env`, keep the project key on the backend, and restart Python.
The existing Realtime adapter remains available through `VOICE_VOICE_PROVIDER=realtime`.
Provider access and audible playback still require a live test; a successful SDP exchange
alone does not establish audio quality.

Sideband warnings record an exception category and, when available, a numeric WebSocket
close code. They omit raw events, exception messages and close reasons because these can
contain conversation content. A normal stream end without finalization is reported separately.
At INFO level, delegation interruption logs distinguish client requests, provider speech
and timed provider transcripts. These describe worker cancellation, not every audio interruption.

Feedback remains limited to category, diagnostic ID, interface state, provider and version,
with a pseudonymous quota identity and seven-day retention. It does not save conversations,
audio or transcripts, and its ID is not a session-log correlation key. Use the report time
alongside local server logs. Do not paste keys or invitation codes into bug reports.

## Opt-in local session recording

For development only, set `VOICE_DEBUG_RECORDING=true` in the root untracked `.env`
and restart the backend. Keep `VOICE_ENVIRONMENT=development`. Run the frontend with
`pnpm dev` from `frontend/`, select Live voice, and check **Record this session for local
debugging** before starting. Consent resets when the session ends. Production builds
hide the checkbox and a non-development backend refuses the debug configuration.

This is separate from feedback. With consent, the backend writes transcripts, normalized
provider-event categories, worker interruptions, consent and close events. The browser
uploads selected incoming-audio WebRTC counters every two seconds (lost/received packets,
jitter, concealed samples and audio level where supported), peer-state changes, local
worker-interruption requests and explicit stop events. A timestamp accompanies each record.
Statistics are browser-reported observations, not proof of provider latency or audio quality.
Tab closure, network failure or a full file can leave gaps; this is not a complete traffic capture.

Files are stored under `VOICE_DEBUG_DIRECTORY` (default `.local/debug`) as
`<session-id>.jsonl`; the interface shows the filename. The directory has mode 0700 and files
0600. Read the JSONL locally with your editor; do not commit or post it publicly. Spoken
personal information can appear in transcripts. No audio, SDP, candidate addresses, device
identifiers, request credentials or raw provider payloads are collected. Feedback remains
content-free even when this separate recorder is enabled.

Each file is capped at 2 MiB and at most 20 files are retained. Recording stops on a storage
error or size limit. The running debug-enabled backend removes files older than 24 hours;
cleanup also runs when creating a recording. If the backend is stopped, files remain until
it runs again or you delete them. Delete individual recordings in `.local/debug` whenever
finished. Uncheck recording for the next session or set `VOICE_DEBUG_RECORDING=false` and
restart to disable the feature. Never enable broad HTTP/header/body debug logging.

### Optional audio download

The separate **Record audio locally** checkbox records microphone and assistant audio
into one mixed track in the browser. It is unchecked initially and resets after the session.
It does not enable transcript recording, upload the recording to the backend, or attach it to feedback.
Live audio still travels to the voice provider as part of the normal conversation.
After Stop, use **Download session audio** and keep the file locally for playback. The browser
chooses WebM/Opus, Ogg/Opus or MP4 according to supported recording formats. A supported
MediaRecorder and Web Audio implementation are required; failure is reported before the
provider offer is sent when recording initialization fails.

Capture stops at five minutes or approximately 20 MiB (checked at one-second chunk
boundaries). The call may continue after capture stops. No recording is started unless you
check the audio box. Both voices are included even if assistant playback is muted. Download
before reloading, closing the tab, leaving Live voice or starting another recording: the
unsaved blob is held only in browser memory and is not backed up. Browser crashes can lose it.
Deleting a downloaded file is your responsibility; the backend's 24-hour cleanup does not
apply to downloads. Do not record other people without their knowledge and agreement.
