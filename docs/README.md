# Documentation

Start with the [project README](../README.md). Pick the path that matches what you want to do.

## Use it

| Guide | What it covers |
|---|---|
| [Local development](local-development.md) | `make be` / `make fe`, the `.env` template, Codespaces |
| [Personal API keys](personal-api.md) | Sessions on your own provider accounts, without an invitation |
| [Session controls](session-ui.md) | Provider choice, language, recovery and recording options |
| [Cost estimates](cost-estimates.md) | What the per-session estimate includes and how prices are versioned |
| [Mobile shells](mobile.md) | The opt-in Capacitor builds for iOS and Android |

## Deploy and operate it

| Guide | What it covers |
|---|---|
| [Deployment](../deployment/README.md) | Vercel frontend, Railway API (Infrastructure as Code), variables, offline stack |
| [Operations runbook](operations.md) | Invitations and access requests, quotas, resets, rollback, diagnostics |
| [Configuration reference](configuration.md) | Every setting, its default and its bounds (generated) |
| [Azure setup](azure-setup.md) | Creating the `gpt-live-1` deployment and its endpoint |
| [ElevenLabs integration](elevenlabs.md) | Agent prompt, the `delegate_task` webhook tool and its authentication |
| [Production scope](production.md) | What this reference does and does not provide for a real service |

## Understand it

| Guide | What it covers |
|---|---|
| [Architecture](architecture.md) | Components, session ownership, delegation and limits |
| [Session flow](session-flow.md) | One conversation from creation to cleanup, including recovery |
| [Worker](worker.md) | Planners, tools, prompts and remote execution |
| [HTTP API](api.md) | Every endpoint, its payload and its errors |
| [Decisions](decisions/README.md) | Architecture decision records |
| [Benchmarks](benchmarks.md) | How voice timing is measured, and what it does not prove |
| [Future extensions](future-extensions.md) | Proposals: MCP, moderation, SIP and a cascaded pipeline |

## Internals and history

[Roadmap and evidence log](roadmap.md), [glossary](glossary.md), the
[live verification checklist](milestones/live-verification.md) and the per-milestone records
in [milestones/](milestones/). These record how features were verified; they are not needed
to use or deploy the project.
