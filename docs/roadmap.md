# Roadmap

What exists today and what each area needs before a v1.0 tag. v0.x tags are
implementation releases (amended 2026-10-05); v1.0 is the first acceptance-gated tag.
Offline tests and CI prove behavior against fakes, not live voice quality or latency.

The maintainer has used GPT-Live (2026-10-23, English and Italian, spoken arithmetic),
Azure as primary provider and ElevenLabs on the deployed backend (2026-11-03). No
recordings or conversation content are published as evidence.

| Area | What exists | Next gate |
|---|---|---|
| Voice and sessions | FastAPI, GPT-Live, WebRTC, React, session cleanup | Recorded microphone session with cleanup checks |
| Delegated worker | LangGraph, read-only tools, timeouts, bounded results | A spoken delegated result in the live checklist |
| Providers and recovery | Azure adapter, opt-in recovery with a new peer and bounded history | A live injected failure that recovers within budget |
| Measurement and evals | OTel, Prometheus, Grafana, reproducible worker evals | Measured latency and a recorded demonstration |
| Public demo | Named invitations, durable quotas, Railway and Vercel deployment | Hosted end-to-end run by an external user |
| Documentation use case | Cited search over public project documentation | Live narration of a cited answer |
| Voice experience | Language and translate controls, interruption recap, accessibility | Live multilingual evaluation |
| Scaling | Two APIs, separate bounded worker, shared leases, crash and load tests | Hosted real-voice run (same-host by design) |
| Quality and feedback | Recovery UX, diagnostic feedback, 40-case eval runner | Accessibility audit and a private pilot ([record](milestones/m9.md)) |

Cross-host high availability is a further architectural change, not part of v1.0.
Supporting records: [Azure setup](azure-setup.md), [provider recovery](milestones/m3.md),
[measurement](milestones/m4.md), [voice and scaling verification](milestones/m7-m8-verification.md)
and [observability](../observability/README.md).

## Evidence log

The sections below record how each feature was verified, in the order it landed.

### Live demonstration preparation

Audio playback instrumentation is opt-in (`VOICE_AUDIO_TIMING`), with deterministic
energy/state tests and bounded numeric telemetry. The expanded
[live checklist](milestones/live-verification.md) covers GPT-Live, audio measurements,
Azure recovery and existing hosted invitation flows. No paid calls or new live
results were collected for this change. Formal live/hosted acceptance remains pending.
The [two-minute storyboard](demo-video.md) marks continued speech during delegated work
and silence-gated delivery as dependent on enabling and live-validating the optional intent-cancellation path.

### One-command offline demonstration

The demo stack combines the frontend, fake-provider session API, separate OfflinePlanner
worker and observability in one Compose command. The container smoke verifies a delegated
calculation and its exported metric without provider keys or paid calls. Browser tests
verify display and ownership cleanup with deterministic responses. Cold builds require
registry access; the 60-second goal applies to a warm cache, not initial provisioning.
Hosted Codespaces acceptance was performed by the maintainer on 2026-10-25:
manual startup with `https://localhost:8080` completed an offline delegation;
Prometheus and Grafana operation panels received metrics. The automatic hook and
single-origin configuration failed in that run. The readiness wait, persisted origin
list and explicit delegation panel address those failures; hosted rerun of these fixes
remains pending. Tested commit, codespace creation minutes and cold Compose minutes
were not recorded. No cold-start duration or new live-voice result is claimed.
Live voice, Azure recovery and hosted invitation acceptance retain their existing status.

### Intent cancellation and pending delivery

The optional task portfolio supports two jobs, explicit per-task cancellation, silence-gated
bounded delivery and preservation through reconnect. Decisions cancellation is independently
disabled by default; fake classifications verify control behavior, not semantic accuracy.
Offline tests cover speech during work, cancellation races, freshness, expiry and classifier
failures. No new paid calls or measured live results are claimed. See
[ADR 009](decisions/009-cancellation-is-intent.md). Both flags remain off in the hosted configuration.

A user-reported local conversation showed a calculation result arriving after continued
speech. This is exploratory evidence, not a measured acceptance run. Follow-up offline
regressions cover frozen terminal task durations, grouped transcript bubbles and explicit
provider-delivery wording. Full playback, concurrent-task and cancellation acceptance
remain to be recorded with the live checklist.

Further offline regressions reconstruct overlapping transcript fragments for recap and
context-dependent requests, and separate worker execution from delivery wait. Opted-in
debugging now records portfolio lifecycle events and the correct worker state. Live behavior
for context-dependent calculations and suppressing unwanted parts of compound results still
needs verification. Spoken cancellation remains advisory only when its Decisions flag is enabled;
with that flag off, use the task Cancel control to stop work.

The correction path now explicitly supplies the previous user turn to the worker, with
instructions to prefer the recent topic over an unrelated older tool result. Offline tests
verify this input contract; semantic reference resolution still requires live validation.
Task durations display one decimal place, and recap labels no longer imply that the latest
assistant excerpt answers the latest user request.

A [four-call live Decisions smoke](milestones/decisions-live-smoke.md) on 2026-10-25
returned two valid non-cancellation decisions and two one-second timeouts. Explicit
semantic cancellation remains unverified; the feature stays off by default.
Browser connection sounds are enabled by default with a preference to disable them;
offline tests cover connection, closure, repeated events and unavailable audio.

### Optional Decisions worker planner

The experimental `VOICE_WORKER_MODE=decisions` adds dynamic tool selection through
choice questions while retaining the existing voice tool and worker limits. Default
worker execution remains offline. Deterministic tests cover selection, final-only text
generation, refusal, malformed responses, timeout fallback, cancellation, client cleanup
and the shared call budget in comparisons. The `worker-v4` comparison records per-case
tool selection, steps, local worker duration and configured token-cost estimates.

The offline run uses scripted stand-ins for both model paths; its perfect selection
signals are harness checks, not evidence of live model quality. No paid planner run
has been performed for this feature. Live comparison, billing validation and
natural-language argument coverage remain pending. See [worker guide](worker.md#decisions-worker-planner)
and [comparison procedure](../evals/README.md#planner-comparison).

### Capacitor mobile preview

The optional [mobile scaffold](mobile.md) packages local React assets for iOS/iPadOS
and Android. Packaging and live voice require explicit opt-in; native voice is off by
default. Deterministic tests cover build guards, native voice gating, background
cleanup and native Origin policy. An unsigned iOS Simulator build was verified on
2026-11-01 with Xcode 27.1 and iOS Simulator SDK 27.1. Android debug and instrumented
test APK compilation were also verified; instrumented tests were not run. Simulator launch,
physical-device audio, Bluetooth, native recording export and store distribution
remain pending. No live provider call or deployed configuration change is claimed.

### Reproducible voice benchmark preparation

The [benchmark page](benchmarks.md) defines 30 fixed delegation cases, with separate
required, direct and ambiguous labels. Offline tests exercise deliberately imperfect
scoring, missing evidence, timing censoring and artifact provenance. The browser harness
observes a real local WebRTC tone loopback without a provider; this verifies measurement
plumbing, not voice recognition or model quality. Paid comparison runs require explicit
opt-in, a clean source revision, hashed local WAV inputs and an exact session budget.

GPT-Live, OpenAI Realtime and Azure comparison results remain pending. ElevenLabs remains
unsupported until its transport evaluation and adapter are approved. No paid calls,
new deployment, measured provider latency or new live acceptance are claimed. The current
Grafana stack has no retained trace data source; the optional trace exporter is verified
with offline mocks and requires an existing Tempo-backed Grafana for a real export.

### Public web search in the worker

Optional Tavily search is implemented behind `VOICE_WEB_SEARCH=false` by default.
Offline HTTP fakes verify bounded results, domain filtering, fallback, cancellation,
private-worker source propagation, citations and rejection of tool calls after web
results. Ten versioned external-information cases exercise search/citation wiring;
they are synthetic fixtures, not evidence of live retrieval quality. System prompts
are packaged Markdown resources. Live relevance, narration and provider account
acceptance remain pending. See [worker setup](worker.md#optional-public-web-search)
and [ADR 011](decisions/011-read-only-web-search.md).

Review regressions also cover whitespace at excerpt cutoffs, voice capabilities that
match the configured planner, and citation loss during local, private-worker and
delayed-result clipping. Uncited clipped web results fail rather than being reported
as successfully delivered evidence. These remain offline checks, not live acceptance.

### Local development commands

Repository-local `make be`, `make fe` and `make invite` commands provide a reusable
local invitation without rewriting existing configuration or credentials.

### Configuration naming and worker model migration

`VOICE_ADAPTER` replaces the ambiguous voice-provider selector name, with the old
name accepted as a deprecated alias. New worker/eval defaults use GPT-6 Luna with
Chat Completions reasoning disabled for tool calling. Offline request-format and
alias-precedence checks are separate from live model acceptance, which is pending.
Existing explicit environment overrides are not silently changed.

### Current entry-point documentation

The README now distinguishes scripted browser playback, real offline worker execution,
reported local live smoke tests and remaining acceptance. The server template lists
current settings with all optional features off; the generated configuration reference
includes enum choices, collection/string constraints and frontend build options.
Copyable local model-backed setup is documented without changing private credentials
or cloud deployments. No new live acceptance or measured model comparison is claimed.

### ElevenLabs transport evaluation and implementation

The [transport decision](decisions/012-elevenlabs-agents-webhook.md) selects private Agents WebRTC with one
async server webhook for delegate_task. The browser owns SDK media and activity/transcript
observations; the backend owns tool admission, the existing worker and bounded HTTP result
delivery. The earlier client-tool forwarding and browser result polling have been removed.

Offline fixtures verify auth/conversation binding, constrained agent configuration, coalesced
replay, independent tasks, cancellation, response deadlines and SDK lifecycle. Identical goals
reuse a task/result for the entire conversation. This is application replay policy, not native
provider exactly-once evidence. Live audio, webhook reachability, async narration, device and
closure acceptance remain pending. See [the implementation guide](elevenlabs.md). No paid
calls or cloud/account changes were made.

### Session cost estimates

Session accounting is enabled by default and uses versioned prices, observed voice duration,
and numeric usage for the worker, Decisions, and search. Offline arithmetic, isolation and remote propagation are verified.
Live billing reconciliation is pending; see [cost estimates](cost-estimates.md).

### Session controls

The automatically enabled [session UI](session-ui.md) provides server-controlled provider selection,
observed audio activity and cost breakdowns. Offline and narrow-viewport checks are verified;
actual device/provider voice acceptance remains pending.

### Personal API sessions and simpler runtime defaults

The voice workspace offers invited Platform API access and invitation-free personal keys.
Provider and worker clients are isolated per personal session, keys are not persisted,
and a distinct private-worker endpoint prevents accidental platform-key use by old workers.
Costs, controls, timing and intent cancellation are automatic; credential presence enables
search and ElevenLabs, while native clients filter ElevenLabs out. Offline contracts are
covered by tests; live account billing and device audio acceptance remain pending. See
[personal-key access and migration](personal-api.md).

## Future extension milestones

These are planned work, with neither offline nor live acceptance claimed. The
[future extension guide](future-extensions.md) records diagrams, prerequisites, proposed
switches, failure behavior and test gates. No implementation is enabled by these notes.

| Planned milestone | Scope | Gate |
| --- | --- | --- |
| Moderation | Opt-in origin-aware hook for goals and tool evidence ([ADR 013](decisions/013-moderation-boundary.md)); offline adversarial fakes | Authorized quality evals; raw transcript segments |
| Worker MCP client | Opt-in audited read-only client ([ADR 010](decisions/010-mcp-trust-model.md)); offline fake-server suite | Live server compatibility; ICS example |
| SIP, optional | Authenticated telephone admission and direct provider media | Admission ADR; authorized carrier smoke |
| Cascade, optional | STT/text/TTS adapter behind explicit audio-relay capability | Privacy/relay ADR; measured comparison |
