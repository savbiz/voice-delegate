# Roadmap

Version 0.1.0 is a reference implementation; implementation and release acceptance are separate. Passing offline tests is not proof of
live voice quality, provider access, acoustic latency or production readiness.

On 2026-10-23, the maintainer reported successful local GPT-Live conversations,
English/Italian transcripts and spoken arithmetic responses after the worker fixes.
This is a partial local smoke test, not completion of the live acceptance checklist.
Azure recovery, measured latency and hosted end-to-end acceptance remain pending.
No recordings or conversation content are published as release evidence.

| Feature | Scope | Acceptance | Current status |
|---|---|---|---|
| Voice and sessions | FastAPI, GPT-Live, WebRTC, React, session cleanup | Real microphone conversation and resource cleanup | Implemented; live verification pending |
| Delegated worker | LangGraph, read-only tools, timeout, bounded results, interruption cancellation | Delegated result is spoken; interrupted work cannot return late | Candidate; offline checks pass; live verification pending |
| Providers and recovery | Azure fallback, new peer, bounded history, duplicate protection | Injected failure recovers within configured budget | Implemented; offline/browser checks pass; Azure live validation pending |
| Measurement, evals and v0.1 | OTel, metrics, Prometheus, Grafana, reproducible evals, docs, recorded demo | CI green, measured latency, live checks and demonstration | Implemented candidate; release evidence incomplete |
| Controlled public demo | Verified deployment, authentication, per-user quotas, application spending limits, private logs, rollback | External users can try it with bounded consumption and protected credentials | Implemented candidate: personal invites, durable quotas, local container checks; hosted acceptance pending |
| Complete use case | Read-only questions over public project documentation with source citations | Useful end-to-end workflow beyond calculator | Implemented: cited documentation search and worker tool; hosted/live narration acceptance pending |
| Advanced voice experience | Multilingual behavior, translation, interruption-aware summaries, accessibility, additional providers | Multilingual and user-correction scenarios pass | Implemented candidate: language/translate controls, interruption recap, accessibility and Realtime adapter; live language evaluation pending |
| Scaling | Multiple instances, session ownership, separate workers, backpressure, load tests | Recovery and isolation work across processes under load | Implemented same-host reference: two APIs, separate bounded worker, shared leases, ownership routing and crash/load tests; hosted real-voice acceptance pending |
| Measured quality and feedback | Versioned task evaluations, clear recovery states, minimal diagnostic feedback | Regression reports, verified recovery UX and bounded feedback from a private pilot | Recovery UX, feedback and 40-case worker eval runner implemented; Braintrust upload verification, accessibility audit and pilot pending; see [quality and feedback record](milestones/m9.md) |

All nine milestones have implementation and offline verification. Release acceptance
still requires the listed live/hosted evidence. Same-host scaling deliberately targets multiple processes on
one host; cross-host high availability is a further architectural change.

See [Azure setup](azure-setup.md), [provider recovery](milestones/m3.md), [measurement](milestones/m4.md), and
[observability](../observability/README.md). Acceptance-gated tags beginning at v1.0 require the listed evidence;
implementation commits alone do not close a milestone.

The [voice experience and scaling verification record](milestones/m7-m8-verification.md) records passing local checks and
the successful Docker rerun, separately from the live and hosted acceptance still required.

Amended 2026-10-05: v0.x tags are implementation releases; acceptance-gated tags begin at v1.0.

## Live demonstration preparation

Audio playback instrumentation is opt-in (`VOICE_AUDIO_TIMING`), with deterministic
energy/state tests and bounded numeric telemetry. The expanded
[live checklist](milestones/live-verification.md) covers GPT-Live, audio measurements,
Azure recovery and existing hosted invitation flows. No paid calls or new live
results were collected for this change. Formal live/hosted acceptance remains pending.
The [two-minute storyboard](demo-video.md) marks continued speech during delegated work
and silence-gated delivery as dependent on enabling and live-validating the optional intent-cancellation path.

## One-command offline demonstration

The demo stack combines the frontend, fake-provider session API, separate OfflinePlanner
worker and observability in one Compose command. The container smoke verifies a delegated
calculation and its exported metric without provider keys or paid calls. Browser tests
verify display and ownership cleanup with deterministic responses. Cold builds require
registry access; the 60-second goal applies to a warm cache, not initial provisioning.
Codespaces configuration is supplied; hosted Codespaces acceptance remains pending.
Live voice, Azure recovery and hosted invitation acceptance retain their existing status.

## Intent cancellation and pending delivery

The optional task portfolio supports two jobs, explicit per-task cancellation, silence-gated
bounded delivery and preservation through reconnect. Decisions cancellation is independently
disabled by default; fake classifications verify control behavior, not semantic accuracy.
Offline tests cover speech during work, cancellation races, freshness, expiry and classifier
failures. No new paid calls or measured live results are claimed. See
[ADR 009](decisions/009-cancellation-is-intent.md). Both flags remain off in the hosted configuration.
