# voice-delegate

[![ci](https://github.com/savbiz/voice-delegate/actions/workflows/ci.yml/badge.svg)](https://github.com/savbiz/voice-delegate/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

[![release](https://img.shields.io/github/v/release/savbiz/voice-delegate)](https://github.com/savbiz/voice-delegate/releases)

**A fast voice conversation. A separate worker for the heavy lifting.**

Talk to a real-time voice model and keep talking while slower work happens in the
background. The voice model knows exactly one tool, `delegate_task`. A bounded LangGraph
worker does the calculation, cited project-documentation lookup or optional web search,
and the answer is spoken when you pause. Interrupting the voice never throws that work away.

<p align="center">
  <img src="docs/images/workspace.png" alt="The voice workspace: provider choice, API access and invitation code" width="720">
</p>

- **Three voice providers, chosen per session:** OpenAI GPT-Live, Azure (a GPT-Live
  deployment) and ElevenLabs Agents.
- **Background delegation:** up to two tasks run at once; results wait for silence and
  carry the original request.
- **Your keys or the platform's:** bring your own provider keys (memory only) or use an
  invitation code with daily quotas.
- **Cost estimates** per session, optional Azure recovery, OpenTelemetry metrics and an
  opt-in iOS/Android shell.

## How it works

```mermaid
flowchart LR
    U["You speak"] <-->|WebRTC audio| V["Voice model"]
    V -->|delegate_task| A["FastAPI session owner"]
    A --> W["LangGraph worker"]
    W --> T["Calculator · project docs · web search"]
    W -->|bounded, cited result| A
    A -->|after a silence| V
```

Audio flows directly between the browser and the voice provider. The backend owns the
session, admission, quotas and delegated work; the voice model never sees the worker's
individual tools.

## Try it

- **Hosted:** open [voice-delegate.vercel.app](https://voice-delegate.vercel.app). Choose
  **Your API keys** to use your own provider account, or **Platform API** with an
  invitation code. No code? Use **Request access** on the page and the maintainer is notified.
- **No keys at all:** **Tools & examples → Offline example** plays a scripted session
  for free, with no microphone or backend.
- **Locally:** follow the steps below.

## Run it locally

Prerequisites: Python 3.12 or 3.13, uv, Node.js 24, pnpm 11.19.0 and make. From the
repository root, install dependencies once:

```sh
uv sync --locked
if [ ! -e .env ]; then cp config/local.env.template .env; fi
cd frontend
pnpm install --frozen-lockfile
cd ..
make fe
```

Open **http://localhost:5173** for the voice workspace. For a scripted example, open
**Tools & examples → Offline example** or **http://localhost:5173/#demo**. The example
is silent and free: no microphone, backend or provider key is required.

For local live voice, put your real `OPENAI_API_KEY` in the private root `.env`.
Start the backend in another terminal, then get the local invitation in a third:

```sh
make be
```

```sh
make invite
```

Paste that invitation in the browser and select **Live voice**. Stop each server
with Ctrl+C. `make` shows help. Existing `.env` values override code defaults; the
launcher changes local admission only, never your file or provider key.

The [minimal template](config/local.env.template) needs only keys and deployment choices.
The worker uses Luna when an OpenAI key is configured, otherwise the offline planner.
You can explicitly select the model-backed planner:

```sh
VOICE_WORKER_MODE=openai make be
```

Voice provider usage and text-worker usage are billed separately. A ChatGPT
subscription does not supply an API key. See the [copyable local configuration](docs/local-development.md#copyable-local-configuration)
and [all variables, allowed choices and bounds](docs/configuration.md).

### One-command offline stack and Codespaces

With Docker running, this starts the API, separate worker, frontend, Prometheus,
Grafana and collector without any provider key:

```sh
bash .devcontainer/start-demo.sh
```

Open **http://localhost:8080** and use **Run offline worker**. Unlike the scripted
browser demo, this executes the real worker graph with a deterministic planner.
See [offline stack](deployment/README.md#offline-stack-in-one-command) for inspection
and shutdown commands. Codespaces uses the same stack; keep forwarded ports private.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/savbiz/voice-delegate)

## Status

v0.2.0 is an implementation release: offline tests and hosted CI cover every feature,
and the maintainer has used each voice provider live. Formal, recorded acceptance is the
gate for v1.0.

| Area | Works today | Not yet claimed |
|---|---|---|
| OpenAI GPT-Live | Live conversations and tool use (maintainer) | Recorded acceptance checklist |
| Azure | Live sessions as primary provider (maintainer) | Live recovery, measured latency |
| ElevenLabs Agents | Live on the deployed backend (maintainer, 2026-11-03) | Formal acceptance, cost reconciliation |
| Worker and delegation | Offline suite, worker evals, a small live Decisions smoke | Live Luna evaluation, cancellation quality |
| Hosted demo | Vercel frontend, Railway API, invitations and quotas | Cold-start timings |
| Native shells | iOS Simulator and Android debug builds compile | Device audio, store publication |

Evidence and remaining gates: [roadmap](docs/roadmap.md),
[live checklist](docs/milestones/live-verification.md) and [benchmarks](docs/benchmarks.md).
The hosted API is on [Railway](https://voice-delegate-api-production.up.railway.app/healthz);
application allowances and provider credits are independent, see [operations](docs/operations.md).

## Providers and worker modes

`VOICE_ADAPTER` selects the default integration (`VOICE_VOICE_PROVIDER` and the values
`live`/`realtime` are deprecated aliases for `openai`). Azure needs a `gpt-live-1`
deployment. Azure recovery is off unless the session checkbox enables it. All adapters
share the same delegation boundary; see [the session flow](docs/session-flow.md).

| Adapter | UI label | Voice service and transport |
|---|---|---|
| `openai` | OpenAI · GPT-Live | OpenAI GPT-Live; browser WebRTC audio and backend sideband (default) |
| `azure` | Azure | Azure `gpt-live-1` deployment; browser WebRTC and backend sideband; also the optional recovery target |
| `elevenlabs` | ElevenLabs · Agents | ElevenLabs Agents; browser SDK WebRTC and an authenticated backend webhook (deployed backend only) |

ElevenLabs requires its private backend API key, agent ID and shared webhook token;
see [agent setup and authentication](docs/elevenlabs.md). The browser receives a
short-lived conversation token, never the private provider key.

Provider selection, observed audio activity and responsive session panels are enabled
by default. Provider choice is fixed for each conversation;
this selector uses operator-configured credentials, not user-supplied keys.
[Session controls](docs/session-ui.md) describe availability and unsupported preferences.

[Cost estimates](docs/cost-estimates.md) are enabled by default. The UI retains a final
breakdown by voice, worker, decisions and search, labeling missing prices as partial. When available, ElevenLabs
reported credits/USD are shown separately; estimates are not a provider invoice.
Cross-vendor fallback, SIP telephone entry and worker MCP connections are not implemented.
The [roadmap](docs/roadmap.md) tracks these and moderation/cascade design work separately.

The UI also offers **Your API keys** without an invitation. Keys are submitted once and
kept in memory for that session, including in a configured private remote worker; they
are not saved to browser storage or a database. **Platform API** uses the operator's keys
and existing invitation gate. Personal sessions never borrow platform keys or recovery.
ElevenLabs additionally needs your private agent ID and its configured webhook token.
See [personal-key access](docs/personal-api.md).

The worker uses **LangGraph for orchestration** and a selected planner for decisions:

| `VOICE_WORKER_MODE` | How a step is chosen | External usage |
|---|---|---|
| `offline` | Deterministic scripted planner, real local tools | No model calls |
| `openai` | Text model selects tools and writes the final answer | OpenAI; configurable model, default `gpt-6-luna` |
| `decisions` | Decisions chooses an action; code builds supported arguments, text model writes the answer | OpenAI Decisions and text-model calls |

`VOICE_WORKER_EXECUTION=local` runs that graph inside the API process. `remote`
uses a separately started private HTTP worker service; it can be another container
on the same machine. It does not automatically deploy another service. Both modes
retain the selected planner and limits. See [worker configuration](docs/worker.md).

The worker has `calculate` and `search_documentation`. Optional `web_search` needs
a private Tavily key on the worker host; providing that key enables search and may incur
search-provider charges. A web result is untrusted data and
ends further tool selection for that delegation. The voice model still sees only
`delegate_task`, never these individual tools. [Prompts](agent/src/voice_delegate_agent/prompts/)
are versioned with the worker.

[Voice instructions and session design](docs/architecture.md).

## Interruption, cancellation and delivery

The default work/narration lifecycle preserves tasks through speech interruptions:

- Speaking interrupts narration while delegated work continues.
- Up to two tasks run independently; a new delegation does not cancel the previous one.
- Results wait for silence, then are sent to the voice provider, or expire after a bounded wait.
- Explicit UI/API cancellation and session end cancel work. Optional semantic cancellation
  additionally requires `VOICE_DECISIONS_CANCEL=true`; failure leaves work running.

“Result sent” means the provider accepted it, not that the user heard the complete
answer. Interrupted audio is not automatically repeated. Task execution and delivery
wait are shown separately. See [ADR 009](docs/decisions/009-cancellation-is-intent.md).

## Data flow and limits

```mermaid
flowchart LR
    B["Browser / opt-in Capacitor shell"] <-->|WebRTC audio| V["Voice service"]
    B -->|Origin + invitation + session key| A["FastAPI: owned sessions and quotas"]
    A <-->|OpenAI SDP/sideband or ElevenLabs token/webhook| V
    V -->|delegate_task| A
    A --> W["LangGraph worker: local or private HTTP service"]
    W --> P["Offline / OpenAI / Decisions planner"]
    P --> T["Calculator / project documentation / optional web search"]
    W --> D["Bounded result; silence-gated when enabled"]
    D --> A
    A -.-> O["Opt-in OTel, Prometheus and Grafana"]
```

Audio goes directly between the browser and voice provider. Backend-owned sessions,
queues, history, model steps, results and external requests have explicit limits.
Invitations, quota SQLite stores and leases control public access. Provider recovery
creates a new browser peer and replays bounded text, never tool executions.

Browser audio timing measures onset/playback separately
from the always-labeled transcript timestamp gap. A transcript gap is not acoustic
latency; browser measurements are proxies, not a hardware loopback measurement.
See [measurement methodology](docs/benchmarks.md) and [observability](observability/README.md).

Ordinary diagnostics exclude conversation text. Server debug recording requires
explicit session consent; it stores bounded data for up to
24 hours while the backend runs. Audio recording is a separate browser-only consent
and download. The operator can read server debug recordings. See [operations](docs/operations.md).

## Checks

From the repository root:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov=voice_delegate --cov=voice_delegate_agent --cov-fail-under=85
uv run python scripts/check_independence.py
uv run python scripts/check_deployment.py
uv run python scripts/check_links.py
uv run python scripts/build_reference.py --check
uv build --all-packages
```

From `frontend/`:

```sh
pnpm lint
pnpm build
pnpm test
pnpm exec playwright install chromium  # Once, if the browser is not installed.
pnpm test:e2e
pnpm test:stack
```

CI checks Python 3.12 and 3.13, builds/smokes the backend and offline demo containers,
and syncs the opt-in native scaffold. Python tests disable external sockets; browser
tests use local fakes. Installing dependencies/browsers needs internet; testing does
not require provider credentials or paid requests.

## Documentation

- [Architecture](docs/architecture.md), [API](docs/api.md), [glossary](docs/glossary.md) and [ADRs](docs/decisions/)
- [Configuration](docs/configuration.md), [local development](docs/local-development.md), [worker setup](docs/worker.md)
- [Deployment](deployment/README.md), [operations](docs/operations.md), [production scope](docs/production.md)
- [Benchmarks](docs/benchmarks.md), [worker evals](evals/README.md), [roadmap and acceptance](docs/roadmap.md)
- [Session controls](docs/session-ui.md), [ElevenLabs setup](docs/elevenlabs.md), [cost estimates](docs/cost-estimates.md)
- [Native packaging](docs/mobile.md), [third-party notices](THIRD_PARTY_NOTICES.md) and [contributing](CONTRIBUTING.md)

- Future work: [MCP, moderation, telephone SIP and a cascaded voice pipeline](docs/future-extensions.md) (proposals only)

Public protocol sources are cited in the design documents and ADRs.

## Independence and licence

This is a personal project by Savino Bizzoca. It is independent and not affiliated with,
endorsed by, or derived from my employer's products, code or internal information. It is
also not affiliated with or endorsed by OpenAI, Microsoft Azure or any other provider
named in this documentation; product names are used descriptively.

Copyright 2026 Savino Bizzoca. Licensed under [Apache-2.0](LICENSE); dependencies and
bundled data retain their individual licence terms ([notices](THIRD_PARTY_NOTICES.md)).
