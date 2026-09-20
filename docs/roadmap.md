# Roadmap M1–M8

Implementation and release acceptance are separate. Passing offline tests is not proof of
live voice quality, provider access, acoustic latency or production readiness.

| Milestone | Scope | Acceptance | Current status |
|---|---|---|---|
| M1 — Voice and sessions | FastAPI, GPT-Live, WebRTC, React, session cleanup | Real microphone conversation and resource cleanup | Implemented; live verification pending |
| M2 — Delegated worker | LangGraph, read-only tools, timeout, bounded results, interruption cancellation | Delegated result is spoken; interrupted work cannot return late | Candidate; offline checks pass; live verification pending |
| M3 — Providers and recovery | Azure fallback, new peer, bounded history, duplicate protection | Injected failure recovers within configured budget | Implemented; offline/browser checks pass; Azure live validation pending |
| M4 — Measurement, evals and v0.1 | OTel, metrics, Prometheus, Grafana, reproducible evals, docs, recorded demo | CI green, measured latency, live checks and demonstration | Implemented candidate; release evidence incomplete |
| M5 — Controlled public demo | Verified deployment, authentication, per-user quotas, application spending limits, private logs, rollback | External users can try it with bounded consumption and protected credentials | Planned before public access; existing shared access code is not per-user auth |
| M6 — Complete use case | Read-only questions over public project documentation with source citations | Useful end-to-end workflow beyond calculator | Planned; local notes tool alone does not satisfy this milestone |
| M7 — Advanced voice experience | Multilingual behavior, mirroring, interruption-aware summaries, accessibility, additional providers | Multilingual and user-correction scenarios pass | Planned for v0.2 after v0.1 measurement |
| M8 — Scaling | Multiple instances, session ownership, separate workers, backpressure, load tests | Recovery and isolation work across processes under load | Optional; implement only if actual deployment needs it |

Recommended order: finish the live M1–M4 release gates; implement M5 and M6; measure the
result before M7; decide M8 from load evidence. Azure setup and the remaining live checks
need not prevent offline implementation of M5/M6.

See [Azure setup](azure-setup.md), [M3](m3.md), [M4](m4.md), and
[observability](../observability/README.md). Stable tags require the acceptance evidence;
implementation commits alone do not close a milestone.
