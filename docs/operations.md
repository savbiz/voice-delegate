# Demo operations runbook

This runbook covers one backend process with a durable local volume, or the bundled same-host topology. It does not claim multi-region availability. See [production scope](production.md) and the generated [settings reference](configuration.md).

## Disable new sessions

Set `VOICE_DEMO_ENABLED=false` on the backend and restart/redeploy every API instance. The setting is read at startup; changing the dashboard value alone does not update an existing process. New session creation returns 503. This is an admission switch, not a provider-side spend cutoff. Restart closes local sessions where possible; a crashed or unreachable provider connection can remain unconfirmed. Reference search and authenticated heartbeat/close do not depend on this switch. Re-enable only after the incident is understood.

## Rotate or revoke an invitation

Edit `VOICE_INVITE_TOKENS`, a JSON map of stable pseudonymous names to unique random tokens of at least 32 characters. Generate a replacement locally with `uv run python -c 'import secrets; print(secrets.token_urlsafe(32))'`. Keep the name unchanged when rotating so its hashed quota identity and reservations remain associated. Remove the name to revoke it. Apply the same mapping to all API instances and restart them. Distribute tokens privately. Never put tokens in URLs, screenshots, issue reports or frontend environment variables. `VOICE_ACCESS_TOKEN` is only for private testing, not the public-demo profile.

Invitations can also live in `VOICE_ACCESS_DATABASE` (SQLite on the volume, codes stored only as SHA-256 hashes). They take effect at once, without a redeploy, and the public demo may run with `VOICE_INVITE_TOKENS={}`. Keep one named code in the variable as an emergency path if the database is ever unavailable.

```sh
make invite-add NAME=alice      # prints the code once
make invite-list                # names and creation dates, never codes
make invite-revoke NAME=alice
```

On Railway, run the module in the deployed container, with `VOICE_ACCESS_DATABASE` set to an absolute path on the volume (for example `/app/.local/access.sqlite3`):

```sh
railway ssh "/app/.venv/bin/python -m voice_delegate.invites add alice"
```

To migrate a variable entry, add the same name to the database, then remove it from `VOICE_INVITE_TOKENS` and redeploy; the name keeps its quota identity, but the code changes. To rotate, revoke and add again.

### Access requests

Set `VOICE_ACCESS_REQUEST_URL` to an HTTPS [ntfy](https://ntfy.sh) topic URL with a long, unguessable topic (for example `https://ntfy.sh/<random-string>`) and subscribe to it in the ntfy phone app. The hosted UI then shows **No invitation code? Request access**. At most five notifications are sent per hour per process and a repeated contact is ignored within the hour. Treat the topic URL as a secret: anyone who knows it can read or post to it. Leave the variable empty to hide the button.

**Notification only** (no `VOICE_PUBLIC_API_URL`): the visitor's contact and optional note are forwarded as one notification and never stored or logged. To reply, add a name to `VOICE_INVITE_TOKENS` as above, redeploy and send the token privately.

**Remote approval** additionally needs `VOICE_PUBLIC_API_URL`, the public HTTPS origin of this API (for example `https://voice-delegate-api-production.up.railway.app`); the notification buttons call it. `VOICE_ACCESS_DATABASE` (default `.local/access.sqlite3`) must be on the persistent volume.

The visitor must then enter an email address. The notification carries **Approve** and **Deny** buttons; each is a `POST` to `/access/{id}/{secret}/approve|deny` with a one-time secret, so only the topic's subscribers can decide. Approve creates a new invitation code, stores only its SHA-256 hash and sends a second notification with the code and two buttons that open an email with the recipient, subject and text (including the code) filled in: **Gmail** opens Gmail's web compose page, which works from the ntfy web app on a phone (it opens links in the browser, where `mailto:` may not reach your mail app), and **Mail app** is a `mailto:` link. That notification is published with `Cache: no`, so ntfy.sh does not keep it after delivery; if it cannot be published, the code is revoked and Approve can be pressed again. The code works at once, without a redeploy. Approved principals are pseudonymous (`email-` plus a hash prefix), so quotas and logs never contain the address. The address and note are deleted when the owner decides or after 7 days; a hash of the address is kept for 30 days to ignore repeated requests (and indefinitely for approved addresses). At most 20 requests are accepted per day.

Approved requests appear in `make invite-list` as `email-<hash>`; revoke them with `invite-revoke` like any other name.

## Quotas and cost controls

- `VOICE_DAILY_SESSIONS_PER_USER` limits sessions reserved per principal per UTC day.
- `VOICE_UNLIMITED_INVITES` (JSON list of invitation names, for example `["savino"]`) exempts those invitations from the daily session and voice-second allowances, so the operator can test without resets. Their sessions do not draw on the global daily budget either; concurrency and session-length limits still apply. Keep the list to your own invitations: provider spend for them is unbounded by these allowances.
- `VOICE_CONCURRENT_SESSIONS_PER_USER` limits active leases per principal.
- `VOICE_MAX_SESSIONS` caps local API sessions and, with shared SQLite, global active leases.
- `VOICE_DAILY_VOICE_SECONDS_PER_USER` and `VOICE_DAILY_VOICE_SECONDS_GLOBAL` cap reserved voice seconds per UTC day for platform-funded sessions in public-demo mode; personal-key sessions skip these daily reservations. Each admitted platform session reserves `ceil(session_ttl_seconds + 1)`, doubled only when the session opts into Azure recovery. Early close and failed connect do not refund the reservation.
- `VOICE_SESSION_TTL_SECONDS` bounds a conversation's lifetime. Heartbeat expiry reclaims abandoned sessions; neither heartbeat nor fallback extends the absolute TTL.
- `VOICE_MAX_DELEGATIONS_PER_SESSION` caps accepted distinct worker requests. An over-limit request does not cancel already-running work.
- Worker step, duration, result-size and concurrency limits cap application-owned work; they are not a dollar-accurate billing meter.
- `VOICE_SESSION_SUMMARY` (default false) adds at most one bounded worker-model call per user-closed conversation (about 2,000 input and 300 output tokens). It is counted as a worker call in the session estimate.

Use project-scoped provider keys. Configure provider budget alerts and available hard spending controls; verify whether the selected provider/account treats a budget as a warning or actually rejects additional use. Monitor billed usage separately from local reserved seconds. Disable new sessions and revoke/disable a provider key if uncontrolled provider usage continues. Never assume a local timeout proves upstream billing stopped.

## Inspect persistent SQLite state

The hosted volume mounts at `/app/.local`; quota and feedback paths must point inside it and be writable by the process. Railway's platform-managed volume ownership may require the documented `RAILWAY_RUN_UID=0` exception; see [deployment](../deployment/README.md). Do not delete or replace the volume to fix an application startup error.

From an administrative shell where the `sqlite3` CLI is available, use read-only queries:

```bash
sqlite3 -readonly /app/.local/quotas.sqlite3 'SELECT day, SUM(sessions), SUM(seconds) FROM reservations GROUP BY day;'
sqlite3 -readonly /app/.local/quotas.sqlite3 'SELECT COUNT(*), MIN(expires), MAX(expires) FROM leases;'
sqlite3 -readonly /app/.local/feedback.sqlite3 'SELECT category, state, COUNT(*) FROM feedback GROUP BY category, state;'
sqlite3 -readonly /app/.local/feedback.sqlite3 "SELECT datetime(created, 'unixepoch'), category, note FROM feedback WHERE note IS NOT NULL ORDER BY created DESC;"
```

Quota principals are hashes, not invitation tokens. Leases expire even if release fails. Reservations roll over by UTC day. Feedback accepts an optional typed note of at most 500 characters (which may contain whatever the reporter writes, so treat it as personal data). When `VOICE_ACCESS_REQUEST_URL` is set, each new report (not a retry) sends a "New feedback to read" notification to that ntfy topic with the category, provider, interface state, the first eight characters of the diagnostic ID and whether a note is attached; the note itself stays on the server, so read it with the query above. A failed notification is logged and the report is still stored. Feedback retains reports for seven days, allows five per principal per rolling 24 hours, and caps storage at 10,000 records. Treat backups as sensitive operational data. Use SQLite's backup mechanism or a quiesced consistent volume snapshot; copying a live WAL database file alone is not a safe backup.

## Reset one invitation’s daily allowance

This is an operator-only exception for a known invitation name, not its secret token.
Close that user's conversations first and take a consistent SQLite backup as described
above. From the repository, open the linked Railway service's administrative shell:

```sh
railway ssh --service voice-delegate-api --environment production
```

Inside that shell, replace `invitation-name` with the exact stable name in
`VOICE_INVITE_TOKENS`, then run:

```sh
python - <<'PYRESET'
import hashlib
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

name = "invitation-name"
if name == "invitation-name":
    raise SystemExit("Set the invitation name first; never paste its token")
principal = hashlib.sha256(name.encode()).hexdigest()
day = datetime.now(UTC).date().isoformat()
uri = Path(os.environ["VOICE_QUOTA_DATABASE"]).resolve().as_uri() + "?mode=rw"
with sqlite3.connect(uri, uri=True, timeout=2) as db:
    db.execute("BEGIN IMMEDIATE")
    active = db.execute(
        "SELECT COUNT(*) FROM leases WHERE principal=? AND expires>?",
        (principal, time.time()),
    ).fetchone()[0]
    if active:
        raise SystemExit("Close active conversations or wait for lease expiry first")
    removed = db.execute(
        "DELETE FROM reservations WHERE day=? AND principal=?", (day, principal)
    ).rowcount
    print(f"Reset {removed} reservation row(s) for {day} UTC")
PYRESET
```

This removes only today's reservation for that identity; it does not delete leases,
other users, historical rows or the database. It also reduces the global total of reserved
seconds for today. Token rotation with the same name does not reset an allowance.
No restart is required. Failed starts and early close normally retain their reservation;
this manual exception is not an automatic refund or evidence that upstream usage stopped.
Provider credits, API-key limits and billing are unaffected.

## ElevenLabs bootstrap and immediate disconnects

Check the stages independently: an application 429 is admission; a bootstrap 502 is
provider setup; a 200 bootstrap followed by immediate close needs the ElevenLabs
conversation's initialization error. The private key needs ElevenAgents write permission
for conversation-token issuance, even when reading agent configuration succeeds.
`quota_exceeded` is a provider account/key quota rejection; inspect the current workspace,
remaining credits and any key-specific usage limit before changing plans. A displayed
balance alone does not establish that the selected call can start.

Architect setup chats can also draw workspace credits. Inspect Agents → Architect →
Usage → Cost separately from agent conversations and simulations. These setup charges
are outside the application session ledger; reading an agent configuration through MCP
is not an Architect chat. See [Architect pricing and usage](https://elevenlabs.io/docs/eleven-agents/operate/architect/pricing).

`finalized=true` means provider closure was confirmed, including a failed call. The bundled
ElevenLabs voice rate is an assumption ($0.08/minute); `unpriced: ["voice.elevenlabs.second"]`
appears only with a custom price file that leaves it out. `adapters` lists the voice providers
the session used. `provider_usage: null` means no provider receipt was available; it is not a
confirmed zero bill. Never log private keys or conversation contents to investigate this.

## Rollback while retaining data

Record the deployed commit/image and settings before rollout. Disable new sessions and drain/close conversations where possible. Redeploy the previously verified commit/image while retaining the same volume, database paths, invitation names and instance IDs. Check schema compatibility before rollback; retain a consistent backup and a tested restore procedure. Do not blindly restore an older quota database, which could erase reservations and permit extra usage. After restart, verify `/healthz`, `/api/config`, an authenticated documentation search and admission behavior. Only then re-enable new conversations. The [live-verification template](milestones/live-verification.md) records voice acceptance separately.

## Diagnose an unconfirmed close

`finalized=false` means local cleanup completed without confirmation for one or more provider connections. Inspect redacted provider/cleanup logs and the provider's usage dashboard. Do not retry an ambiguous session-creation POST: it may create a second billable call. Escalate persistent usage through provider controls. A browser showing “ended” proves local media release, not provider-side finalization.

## Monitor and escalate

The [health workflow](../.github/workflows/health.yml) calls the hosted `/healthz` once a day, allowing for a cold start from app sleeping, and a failed run posts to the ntfy topic in the `HEALTH_NTFY_URL` repository secret (for
example the access-request topic). Without that secret, the only alert is GitHub's failed-run
email, which goes to the schedule actor and depends on their notification settings. Run it on
demand from the Actions tab. It is deliberately infrequent: polling every few minutes would keep the sleeping service awake. An external monitor such as UptimeRobot has the same trade-off.

Check backend health, worker busy/timeouts, provider error/cancelled outcomes, lease counts and provider billed usage. Use [observability](../observability/README.md) for optional local dashboards; hosted alerting and trace retention are operator responsibilities.

### Hosted telemetry (Grafana Cloud)

The backend can export traces and metrics straight to an OTLP service such as the free
Grafana Cloud tier, with no collector:

1. In the Grafana Cloud portal, open your stack, then **OpenTelemetry → Configure**.
   Generate an API token; the page shows the three variables below, filled in.
2. Set them on the Railway API service (the header contains the token, so it is a secret):
   `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`,
   `OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-prod-<region>.grafana.net/otlp` and
   `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <value from the page>`.
3. After the redeploy, run one session. Traces appear under **Explore → Tempo** and metrics
   (`voice_operation_duration_seconds` and the others listed in
   [observability](../observability/README.md)) under **Explore → Prometheus**.

4. Import the two dashboards from [`observability/grafana-cloud/`](../observability/grafana-cloud/)
   (**Dashboards → New → Import**, upload the JSON). They use the stack's default Prometheus
   and Tempo data sources:
   - `overview.json`: connections, delegated tasks, error rate, estimated cost, connect
     p95, interruptions, latency by operation, transcript wait, browser audio timing and
     cost by component.
   - `worker-traces.json`: worker duration and outcomes, cancellations, deliveries,
     moderation reviews, span duration by name, recent traces and slow or failed spans.

   Totals use each backend process's counters (`max_over_time`), because `increase()`
   drops the first sample of every new series and undercounts at demo traffic.

Explicit `VOICE_OTEL_ENDPOINT` and `VOICE_OTEL_METRICS_ENDPOINT` take precedence over the
standard variables. Without any endpoint, traces go to the service log and metrics are not
exported. Exported data contains no transcripts, session IDs, credentials or tool results. For a security issue use the [private reporting channel](../SECURITY.md), not a public transcript or log dump.

## Temporary API documentation

Set `VOICE_API_DOCS=true` temporarily to expose Swagger; default off in production. Restart the backend to apply it. This also exposes ReDoc and the OpenAPI schema without invitation authentication, subject to host and rate middleware. Restore `false` and restart after inspection. Development exposes these routes by default.

## Investigating interrupted audio locally

For a local Live test, set `VOICE_ADAPTER=openai` and `VOICE_MODEL=gpt-live-1`
in the untracked root `.env`, keep the project key on the backend, and restart Python.
Provider access and audible playback still require a live test; a successful SDP exchange
alone does not establish audio quality.

Sideband warnings record an exception category and, when available, a numeric WebSocket
close code. They omit raw events, exception messages and close reasons because these can
contain conversation content. A normal stream end without finalization is reported separately.
At INFO level, delegation interruption logs distinguish client requests, provider speech
and timed provider transcripts. These describe worker cancellation, not every audio interruption.

Feedback remains limited to category, diagnostic ID, interface state, provider, version and an
optional note the reporter types, with a pseudonymous quota identity and seven-day retention. It
does not save conversations, audio or transcripts, and its ID is not a session-log correlation key. Use the report time
alongside local server logs. Do not paste keys or invitation codes into bug reports.

## Opt-in server session recording

Recording is off by default for each session. Check **Record this session for server
debugging** before starting; it is available in both API modes. Consent starts unchecked
and resets at session end. No environment enable flag is needed: the application ignores
the former recording flag. Without checkbox consent, no session recording is created.

For Railway, keep `VOICE_ENVIRONMENT=production` and set
`VOICE_DEBUG_DIRECTORY=/app/.local/debug` on the existing persistent volume.
Deploy the supporting backend and frontend commits together.
The service operator can read these files; there is no public download route.
For local development, the default directory is `.local/debug` in the repository.

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
error or size limit. The running backend removes files older than 24 hours;
cleanup also runs when creating a recording. If the backend is stopped, files remain until
it runs again or you delete them. Delete individual recordings in `.local/debug` whenever
finished. Leave recording unchecked for subsequent sessions. Never enable broad HTTP/header/body debug logging.

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

Consented debug recordings also include `delegation_finished`: the final worker status
and bounded narration text. Rejected tool calls and execution failures are reported as
`failed`, not completed; cancelled work has no delivered result. The text planner requests
one tool call per step and can run calculation and documentation search sequentially.
