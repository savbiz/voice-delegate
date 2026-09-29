# Demo operations runbook

This runbook covers one backend process with a durable local volume, or the bundled same-host topology. It does not claim multi-region availability. See [production scope](production.md) and the generated [settings reference](configuration.md).

## Disable new sessions

Set `VOICE_DEMO_ENABLED=false` on the backend and restart/redeploy every API instance. The setting is read at startup; changing the dashboard value alone does not update an existing process. New session creation returns 503. This is an admission switch, not a provider-side spend cutoff. Restart closes local sessions where possible; a crashed or unreachable provider connection can remain unconfirmed. Reference search and authenticated heartbeat/close do not depend on this switch. Re-enable only after the incident is understood.

## Rotate or revoke an invitation

Edit `VOICE_INVITE_TOKENS`, a JSON map of stable pseudonymous names to unique random tokens of at least 32 characters. Generate a replacement locally with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. Keep the name unchanged when rotating so its hashed quota identity and reservations remain associated. Remove the name to revoke it. Apply the same mapping to all API instances and restart them. Distribute tokens privately. Never put tokens in URLs, screenshots, issue reports or frontend environment variables. `VOICE_ACCESS_TOKEN` is only for private testing, not the public-demo profile.

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
