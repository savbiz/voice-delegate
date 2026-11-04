# Roadmap

What works today, and what comes later. Every feature below has offline tests and runs
in CI. "Used live" means the maintainer has run it against real providers. The README
links a recorded demonstration of the main path. How each feature was verified is in the
[evidence log](milestones/evidence-log.md).

## What works today

| Area | What exists | Used live |
| --- | --- | --- |
| Voice sessions | GPT-Live on OpenAI and Azure, ElevenLabs Agents; WebRTC audio straight to the provider; bounded lifetimes and cleanup | Yes, all three providers |
| Background worker | LangGraph worker with calculator, cited project-docs search and optional web search; up to two tasks at once, delivered after a pause | Yes; 40-case GPT-6 Luna eval: 98% judged correct, 99% grounded (2026-11-04) |
| Recovery | Opt-in single Azure recovery with bounded text history | Not yet recorded |
| Access and quotas | Your own keys, or invitation codes with daily quotas; Request access with phone approval | Yes |
| Costs | Per-session cost estimates from a versioned price snapshot | Estimates only, not reconciled with invoices |
| Safety | Opt-in moderation of goals and tool evidence ([ADR 013](decisions/013-moderation-boundary.md)); read-only MCP client behind it ([ADR 010](decisions/010-mcp-trust-model.md)) | Not yet |
| Observability | OpenTelemetry metrics and traces; local Prometheus and Grafana, or Grafana Cloud with importable dashboards; opt-in debug recordings and feedback reports | Yes, hosted backend to Grafana Cloud |
| Scaling | Two API instances, a separate private worker, shared leases; crash and load tests | Not on hosted voice |
| Deployment | Railway backend (infrastructure as code), Vercel frontend, daily health check | Yes |
| Mobile | Opt-in Capacitor shell for iOS and Android | Simulator build only |

## Later

- Formal live acceptance per provider ([checklist](milestones/live-verification.md)) and a paid
  [voice benchmark](benchmarks.md). Both are optional and stay documented; until they are run,
  no formal acceptance or latency figures are claimed.
- Telephone entry over SIP and a cascaded STT, text model and TTS pipeline, both optional
  ([future extensions](future-extensions.md)).
- Live MCP server compatibility and moderation quality evaluations.
- The OpenSSF Best Practices (bestpractices.dev) self-certification questionnaire, for an
  optional README badge.
- Cross-host high availability (today's scaling is same-host by design).
