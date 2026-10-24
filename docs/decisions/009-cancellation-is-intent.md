# ADR 009: Cancellation is intent; speech pauses narration

Status: accepted 2026-10-24

## Context

Cancelling a worker whenever the user speaks prevents useful conversation during slow
work. A second request need not replace the first. Classification mistakes are asymmetric:
keeping an unwanted calculation costs time, while cancelling wanted work loses its result.

## Decision

`VOICE_INTENT_CANCELLATION=false` retains the existing single-task behavior. When enabled,
up to `VOICE_MAX_INFLIGHT_TASKS` (default and maximum two) jobs occupy independent slots.
Running, pending and delivering jobs count towards this bound; rejected IDs are remembered
within the existing per-session request budget. A new request never cancels an existing job.
The voice model still has only `delegate_task`.

Speech interrupts provider narration, not worker execution. Explicit `/interrupt` cancels
all tasks, or just the optional `task_id`. Session termination cancels all work. A portfolio
cancellation generation advances only when active work is cancelled; per-job state prevents
cancelling one job from invalidating another. Noncooperative workers retain global capacity
until they actually finish. No result is retried after an ambiguous provider send.

Completed results become bounded pending deliverables. The preamble includes a bounded
excerpt of the original goal; the complete commentary remains within the existing token
and 500-byte limits. Delivery requires fresh browser audio-activity reports and at least
`VOICE_DELIVERY_SILENCE_SECONDS` (default 0.6) seconds of observed silence. Reports contain
only booleans, sequence and transport generation. They expire after one second. Missing
analysis or a suspended browser holds results; it never implies silence. After delivery,
an assistant-audio observation is required before another result is narrated. Muting playback
does not hide remote stream energy. Undelivered results expire after
`VOICE_DELIVERY_TIMEOUT_SECONDS` (default 30) and increment an expiry metric.

A provider speech-start or transcript event also resets the silence window. Browser energy
is a delivery heuristic, not proof of physical silence or an atomic provider playback lock.
Speech can start after a send; the provider's own interruption handling remains authoritative.
Cancellation cannot retract audio or commands already accepted upstream.

Transport failure alone preserves work. A reconnect retains jobs, clears stale activity,
and uses the new connection for pending delivery. Realtime receives an untrusted text item
for a result from the old transport instead of an invalid old function-call output. Cancelled
or expired Realtime calls receive a terminal output without a new `response.create`; Live
needs no corresponding function-call output. Terminal acknowledgements are best effort and
never retried if delivery was ambiguous.

## Optional semantic decisions

`VOICE_DECISIONS_CANCEL=false` makes no Decisions calls. Enabling it requires intent mode
and an environment-supplied OpenAI key. `OpenAIDecider` uses `POST /v1/decisions`, model
`gpt-6-luna`, with named `predicate` questions (`type`, `name`, `instructions`). A plain-text
JSON rendering supplies the last assistant excerpt, current user utterance and indexed goals
as evidence. The API also accepts role-based messages; those are unnecessary for this classifier.
Two questions per task ask about cancellation intent and continued relevance. Only cancellation
probability at or above `VOICE_DECISIONS_THRESHOLD` (default 0.85) triggers cancellation.
Relevance alone never cancels. This threshold is a policy default, not a calibrated live result.

Classification runs separately from the event reader. Fragment bursts coalesce into the latest
bounded utterance, with one request in flight per session; stale decisions cannot cancel work.
The timeout defaults to one second, with at most 60 requests/session, at most four questions,
32 KiB input and 64 KiB response. Errors, malformed output, refusals and exhausted budgets
preserve work. There are no retries, new dependencies, or conversation/credential log fields.

Estimated cost counts successful responses' input tokens at a configurable rate, initially
USD 0.10/million (public Decisions pricing checked 2026-10-24). It is not billing: failed
requests, cache write/read differences, regional premiums and long-context adjustments are
not included. Automatic provider caching may apply; no identity-bearing cache key is sent.

## Consequences and verification

This amends [lifecycle ownership](002-lifecycle-and-bounds.md) and
[worker cancellation](005-bounded-delegation.md) only when the opt-in flag is enabled.
The default remains compatible with existing deployments. The UI exposes IDs, abbreviated
goals, elapsed time and per-task cancellation; it does not introduce another voice tool.

Deterministic fake workers, classifiers, sockets, clocks and browser tests cover continued
speech, parallel work, explicit/semantic cancellation, stale decisions, timeout, expiry and
reconnect. No paid calls were made. Classifier accuracy, audible silence delivery and cross-provider continuity remain live pending; the live checklist must measure those separately.

Sources: [Decisions reference](https://developers.openai.com/api/reference/resources/decisions/methods/create),
[Decisions guide and pricing](https://developers.openai.com/api/docs/guides/decisions),
[Live delegation](https://developers.openai.com/api/docs/guides/live-delegation),
[Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations).
