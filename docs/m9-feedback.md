# M9 recovery UX and minimal feedback

The live interface describes worker running, busy, cancelled, timed out, failed,
delivery failed and task-limit states. Cancel is available for running work; ambiguous
cancellation offers a manual retry or Stop. Connection failure retains an explanation and
offers Start conversation after cleanup. Fallback remains bounded to one attempt; neither
busy work nor failed recovery automatically resubmits a task. A heartbeat may take up to
ten seconds to refresh worker status. These are known transport/task states, not inferred
microphone listening or assistant speech detection.

## Feedback contract

`POST /api/feedback` requires the allowed Origin and configured invitation/access code.
Feedback is disabled without server authentication configuration. It does not require a
live session so a user can report a failed connection or a closed conversation.

The request accepts exactly a UUID diagnostic ID, one of five problem categories, and a
finite interface state. Extra fields are rejected. The server adds its configured primary
provider, application version, timestamp and a SHA-256 pseudonym of the authenticated
identity. Provider means configured primary, not proof of which provider handled an event;
interface state is user-reported, not authoritative telemetry. The diagnostic ID identifies
the report, not a stored conversation or transcript. There is no free-text field.

No audio, transcripts, task content, session ID/key, invitation token or provider credential
is stored in this database. The UI explains the submitted fields before the explicit Send
report action. One report is allowed per diagnostic ID; retries of the same payload return
the same ID without inserting another record. A changed payload conflicts, and a different
identity cannot reuse that ID. The UI freezes the payload after the first attempt so an
ambiguous network failure can be retried safely.

## Storage and operations

`VOICE_FEEDBACK_DATABASE` defaults to `.local/feedback.sqlite3`. The existing scaling Compose
volume shares this location across the two API processes. Use the same path and persistent
local volume for all processes; do not use a network filesystem. Transactions serialize
capacity checks and insertion. Limits are five accepted reports per identity in a rolling
24-hour window and 10,000 total retained reports. A shared access code shares its feedback
allowance; use personal invitations for individual allowances.

Records expire after seven days. Cleanup runs at startup, before submission, and hourly
while the app is running; physical deletion can therefore lag expiry by up to an hour under
normal operation. When the app is stopped, cleanup resumes on startup. Storage errors are
reported without content and cleanup retries on the next interval. SQLite secure deletion
is enabled and the database file is owner-readable/writable only. Backups require their own
retention policy; SQLite deletion does not erase independent backups.

There is deliberately no HTTP list/read/export endpoint. Operators can inspect the local
database under host filesystem permissions. Expired rows must be removed before any manual
operator analysis or export; no automated export is implemented in this increment.

## Verification

88 Python tests passed, including schema exclusion, authentication/origin checks, identity
isolation, deduplication, conflicting retries, rate/global limits, persistence and expiry.
TypeScript, production frontend build, 3 frontend unit tests and 9 Playwright scenarios
passed. Browser checks exercise busy work, cancellation, failed fallback without replay,
and retrying a report with an identical payload and diagnostic ID.

Real microphone/provider checks, a manual screen-reader audit, the evaluation corpus and
the private pilot remain open. The previous M8 Docker report predates this increment.
