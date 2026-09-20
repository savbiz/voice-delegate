# Roadmap M1–M9

Implementation and release acceptance are separate. Passing offline tests is not proof of
live voice quality, provider access, acoustic latency or production readiness.

| Milestone | Scope | Acceptance | Current status |
|---|---|---|---|
| M1 — Voice and sessions | FastAPI, GPT-Live, WebRTC, React, session cleanup | Real microphone conversation and resource cleanup | Implemented; live verification pending |
| M2 — Delegated worker | LangGraph, read-only tools, timeout, bounded results, interruption cancellation | Delegated result is spoken; interrupted work cannot return late | Candidate; offline checks pass; live verification pending |
| M3 — Providers and recovery | Azure fallback, new peer, bounded history, duplicate protection | Injected failure recovers within configured budget | Implemented; offline/browser checks pass; Azure live validation pending |
| M4 — Measurement, evals and v0.1 | OTel, metrics, Prometheus, Grafana, reproducible evals, docs, recorded demo | CI green, measured latency, live checks and demonstration | Implemented candidate; release evidence incomplete |
| M5 — Controlled public demo | Verified deployment, authentication, per-user quotas, application spending limits, private logs, rollback | External users can try it with bounded consumption and protected credentials | Implemented candidate: personal invites, durable quotas, local container checks; hosted acceptance pending |
| M6 — Complete use case | Read-only questions over public project documentation with source citations | Useful end-to-end workflow beyond calculator | Implemented: cited documentation search and worker tool; hosted/live narration acceptance pending |
| M7 — Advanced voice experience | Multilingual behavior, mirroring, interruption-aware summaries, accessibility, additional providers | Multilingual and user-correction scenarios pass | Implemented candidate: language/mirror controls, interruption recap, accessibility and Realtime adapter; live language evaluation pending |
| M8 — Scaling | Multiple instances, session ownership, separate workers, backpressure, load tests | Recovery and isolation work across processes under load | Implemented same-host reference: two APIs, separate bounded worker, shared leases, ownership routing and crash/load tests; hosted real-voice acceptance pending |
| M9 — Measured quality and feedback | Versioned task evaluations, clear recovery states, minimal diagnostic feedback | Regression reports, verified recovery UX and bounded feedback from a private pilot | Planned; see [M9 scope and acceptance](m9.md) |

The first eight implementation milestones now have code and offline verification. Release acceptance
still requires the listed live/hosted evidence. M8 deliberately targets multiple processes on
one host; cross-host high availability is a further architectural change.

See [Azure setup](azure-setup.md), [M3](m3.md), [M4](m4.md), and
[observability](../observability/README.md). Stable tags require the acceptance evidence;
implementation commits alone do not close a milestone.

The [M7–M8 verification record](m7-m8-verification.md) records passing local checks and
the successful Docker rerun, separately from the live and hosted acceptance still required.
