# Changelog

## Unreleased

**Breaking:** `VOICE_ALLOWED_ORIGIN` and `VOICE_VOICE_PROVIDER` were removed; the backend refuses to start while either is set and names the replacement (`VOICE_ALLOWED_ORIGINS` as a JSON list, `VOICE_ADAPTER`). The unused OpenAI and Azure Realtime adapters were removed; GPT-Live on OpenAI and Azure plus ElevenLabs Agents remain.

Changed: voice prompts are composed from single-purpose blocks and now include spoken-output and failure rules; `python -m voice_delegate.prompts` prints the text for the ElevenLabs agent. The frontend shell is split into workspace, panel and demo components. Documentation is organised by task in `docs/README.md`, with an ADR index and ADR 012 for the ElevenLabs transport. A daily workflow checks the hosted API.

Added: an optional **Request access** button that notifies the owner through an ntfy topic (`VOICE_ACCESS_REQUEST_URL`); requests are rate limited and never stored. With `VOICE_PUBLIC_API_URL` set, the owner can approve from the notification and receives the new code with a prefilled email to send, without a redeploy. Invitations can be added, listed and revoked in the database with `make invite-add/list/revoke` (or `python -m voice_delegate.invites` on the server), and the public demo no longer requires `VOICE_INVITE_TOKENS`.

Added: the page waits up to 30 seconds for a sleeping backend to start, showing a starting message, before discovering providers; the Railway service is described with Infrastructure as Code in `.railway/railway.ts`.

Changed: the provider menu names OpenAI as "OpenAI · GPT-Live" and Azure simply as "Azure". Documentation: the maintainer reported ElevenLabs Agents working live on the deployed backend on 2026-11-03 (formal acceptance and cost reconciliation remain pending); future-extension proposals added under `docs/`.

Added: an opt-in generated conversation summary at the end of a session (`VOICE_SESSION_SUMMARY`, default off), labelled as generated and falling back to the extractive recap; a Gmail compose button next to the mail-app button in the approved-invitation notification. Problem reports accept an optional typed note (at most 500 characters, kept seven days; pasted keys or codes are rejected), and each new report sends a "New feedback to read" ntfy notification when `VOICE_ACCESS_REQUEST_URL` is set; the note itself stays on the server.

Changed: the recap's latest request joins user turns split by the provider; ElevenLabs Agents voice time is estimated at an assumed $0.08/minute (price snapshot 2026-11-04) and cost summaries list the voice adapters used; the Request access form uses the standard button and is replaced by its confirmation once sent.

Fixed: Approve and Deny in the ntfy web app reported "Failed to fetch" and kept the buttons although the decision succeeded; the `/access/` routes now allow the notification origin to read the result. The root `railway.json` was removed after the Railway Infrastructure as Code cutover.

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
