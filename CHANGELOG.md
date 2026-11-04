# Changelog

## Unreleased

Added: an optional **Request access** button that notifies the owner through an ntfy topic (`VOICE_ACCESS_REQUEST_URL`); requests are rate limited and never stored. With `VOICE_PUBLIC_API_URL` set, the owner can approve from the notification and receives the new code with a prefilled email to send, without a redeploy.

Added: the page waits up to 30 seconds for a sleeping backend to start, showing a starting message, before discovering providers; the Railway service is described with Infrastructure as Code in `.railway/railway.ts`.

Changed: the provider menu names OpenAI as "OpenAI · GPT-Live" and Azure simply as "Azure". Documentation: the maintainer reported ElevenLabs Agents working live on the deployed backend on 2026-11-03 (formal acceptance and cost reconciliation remain pending); future-extension proposals added under `docs/`.

## 0.2.0 - 2026-11-03

Live voice is now the primary workspace, with a per-session choice of voice provider and billing source.

Added: provider selection for OpenAI GPT-Live, Azure GPT-Live and ElevenLabs Agents; **Your API keys** sessions that need no invitation and use isolated, memory-only provider clients; opt-in Azure recovery per session; session cost estimates with a versioned price snapshot; ElevenLabs Agents with authenticated asynchronous webhooks (deployed backend); optional cited web search for the worker; voice benchmarks; an opt-in Capacitor preview for iOS and Android; shared agent skills for Codex and Claude Code. The worker defaults to GPT-6 Luna and local development gains `make be`, `make fe` and `make invite`.

Changed: obsolete feature flags are ignored and capabilities follow credentials; Offline example and Project documentation moved under Tools & examples; clearer errors for rejected Azure origins and unconfigured providers; audio activity is reported only after the transport connects; debug recordings and feedback name the session's adapter.

Verified through offline backend and frontend tests and hosted CI. The maintainer reported successful short OpenAI and Azure voice sessions on 2026-11-03. ElevenLabs live acceptance, native-device acceptance, formal latency measurement and invoice reconciliation of cost estimates remain unverified. The Azure voice rate in the price snapshot is an assumption, not a published meter.

## 0.1.0 - 2026-10-23

Independence statement and third-party attributions added.

Internal use by any organisation requires its own dependency and licence review; [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) provides input, not clearance.

Implemented: owned voice sessions, GPT-Live/OpenAI Realtime/Azure adapters, bounded LangGraph delegation and interruption, one-attempt recovery with text history, optional observability, named invitations and SQLite quotas, cited documentation search, bounded feedback, React voice controls and same-host scaling with a private worker.

Verified through offline backend/frontend tests, hosted CI, recorded local Docker exercises and earlier paid text-worker evaluations. Local GPT-Live conversations and spoken arithmetic responses were reported successful by the maintainer on 2026-10-23. Formal live acceptance, Azure calls, measured voice latency and hosted end-to-end acceptance remain unverified. Tagged as an implementation release; live/hosted acceptance is tracked in [docs/roadmap.md](docs/roadmap.md).

Also included: chronological chat transcripts, explicit opt-in server diagnostics, browser-only audio downloads, tab-scoped invitation persistence, and sequential worker tools with explicit failure outcomes. Security fixes update certifi, OpenTelemetry and Vite; dependency licence notices are regenerated.

See [current roadmap](docs/roadmap.md) and [historical verification](docs/milestones/).
