# Changelog

## 0.3.0 - 2026-11-04

Access to the hosted demo can now be requested and approved from a phone, and the codebase is trimmed for v1: one prompt source, fewer adapters, documentation by task.

**Breaking:** `VOICE_ALLOWED_ORIGIN` and `VOICE_VOICE_PROVIDER` were removed; the backend refuses to start while either is set and names the replacement (`VOICE_ALLOWED_ORIGINS` as a JSON list, `VOICE_ADAPTER`). The unused OpenAI and Azure Realtime adapters were removed; GPT-Live on OpenAI and Azure plus ElevenLabs Agents remain.

Added: a **Request access** button that notifies the owner through an ntfy topic (`VOICE_ACCESS_REQUEST_URL`), rate limited. With `VOICE_PUBLIC_API_URL`, the notification has Approve and Deny buttons; Approve creates a code (stored only as a hash) and sends the owner a second notification with mail-app and Gmail buttons to forward it, with no redeploy. Database invitations with `make invite-add/list/revoke`; the public demo no longer requires `VOICE_INVITE_TOKENS`. The page waits up to 30 seconds for a sleeping backend. An opt-in generated end-of-session summary (`VOICE_SESSION_SUMMARY`). Problem reports accept a short typed note and notify the owner. A daily health workflow with an optional ntfy alert. The Railway service is described with Infrastructure as Code in `.railway/railway.ts`.

Changed: voice prompts are composed from single-purpose blocks with spoken-output and failure rules; `python -m voice_delegate.prompts` prints the text for the ElevenLabs agent. The provider menu reads "OpenAI · GPT-Live", "Azure" and "ElevenLabs · Agents". ElevenLabs voice time is estimated at an assumed $0.08/minute (price snapshot 2026-11-04). The recap joins user turns split by the provider. The frontend shell is split into workspace, panel and demo components. The README is shorter and the documentation is organised by task in `docs/README.md`, with an ADR index, ADR 012 for the ElevenLabs transport and future-extension proposals. CI runs once per pull request push, tests Python 3.13 and runs CodeQL on main and weekly, and skips the frontend job and container build for documentation-only changes, to stay within the free GitHub Actions minutes.

Fixed: Approve and Deny in the ntfy web app reported "Failed to fetch" although the decision succeeded. A fallback end-to-end test no longer assumes one heartbeat per interval.

Verified through offline backend and frontend tests and hosted CI. The maintainer reported ElevenLabs Agents working live on the deployed backend on 2026-11-03; formal live acceptance, cost reconciliation and native-device acceptance remain open.

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
