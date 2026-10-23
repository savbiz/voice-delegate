# Changelog

## 0.1.0 - 2026-10-23

Independence statement and third-party attributions added.

Internal use by any organisation requires its own dependency and licence review; [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) provides input, not clearance.

Implemented: owned voice sessions, GPT-Live/OpenAI Realtime/Azure adapters, bounded LangGraph delegation and interruption, one-attempt recovery with text history, optional observability, named invitations and SQLite quotas, cited documentation search, bounded feedback, React voice controls and same-host scaling with a private worker.

Verified through offline backend/frontend tests, hosted CI, recorded local Docker exercises and earlier paid text-worker evaluations. Local GPT-Live conversations and spoken arithmetic responses were reported successful by the maintainer on 2026-10-23. Formal live acceptance, Azure calls, measured voice latency and hosted end-to-end acceptance remain unverified. Tagged as an implementation release; live/hosted acceptance is tracked in [docs/roadmap.md](docs/roadmap.md).

Also included: chronological chat transcripts, explicit opt-in server diagnostics, browser-only audio downloads, tab-scoped invitation persistence, and sequential worker tools with explicit failure outcomes. Security fixes update certifi, OpenTelemetry and Vite; dependency licence notices are regenerated.

See [current roadmap](docs/roadmap.md) and [historical verification](docs/milestones/).
