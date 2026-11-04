# Changelog

## Unreleased

Changed: the backend image built in CI reuses unchanged layers between runs (BuildKit with the GitHub Actions cache). The Trivy vulnerability scan still builds both images without a cache, on purpose, so it always sees current operating-system packages; a test keeps that distinction.

## Unreleased

Changed: CI caches the Playwright browsers between runs (the uv and pnpm package caches were already in use), and Dependabot now also watches the composite action in `.github/actions/backend`, which it had never scanned. That action was a patch release behind on `setup-uv`; it is updated, and a test requires every composite action's third-party steps to be pinned by commit and watched by Dependabot.

Added: a 90-second demonstration video of the hosted app (a spoken question, a calculation and a cited documentation lookup running in the background) at the top of the README, replacing the static screenshot (`docs/images/workspace.png`, now removed). The roadmap no longer lists it as pending, and `docs/demo-video.md` records what the video covers.

## 0.5.0 - 2026-11-04

This release is about evidence and upkeep rather than new voice features. The project now builds and tests on Python 3.14 and Node.js 26, every dependency is refreshed, and the repository gains load testing, contract fuzzing, property and mutation tests, container and supply-chain checks, signed SBOM provenance, a nightly results page and an OpenSSF Scorecard badge.

Changed: the v1.0 gate is narrowed to a recorded demo video. The per-provider live acceptance runs and the paid voice benchmark are now optional and listed under "Later" in the roadmap; their procedures stay documented and no results are claimed. README and ADR 003 are updated to match. The OpenSSF Best Practices questionnaire is noted as a possible later addition.

Changed: the frontend image unpacks the checksum-verified pnpm tarball itself instead of running `npm install` on it, because OpenSSF Scorecard counts any `npm install` without a hash as an unpinned dependency.

Changed: dependency refresh. Python packages are re-locked to their latest releases (FastAPI 0.141 → 0.162, Pydantic 2.14, websockets 17, langgraph 1.2.19, langchain-openai 1.7 and others), the frontend tools are updated (Vitest 5.1, `@types/node` 26, the ElevenLabs client 1.33, Tailwind 4.3.4) and the build backend `uv_build` is aligned with uv 0.13. The OpenAI chat clients now set `use_responses_api=False`, because langchain-openai 1.7 would otherwise switch some models to the Responses API, which the worker and its cost accounting do not use. pnpm stays on 11.19.0: pnpm 12 writes a second YAML document with its own binaries into `pnpm-lock.yaml`, which the lockfile tests and Dependabot do not expect.

Changed: Dependabot groups only minor and patch updates, one pull request per ecosystem each week. Major updates are no longer grouped, so each arrives as its own pull request that can be reviewed and reverted alone. A test keeps this in the configuration.

Changed: the project now builds and tests on Python 3.14 only (it was 3.12 and 3.13): packages, tools, the backend image and CI. CI has one backend job, `backend (3.14)`, replacing `backend (3.12)` and `backend (3.13)`, so the required checks in the repository ruleset must be updated. A test keeps every place that names the version in agreement. Python 3.14 reports an unclosed HTTP error response, so the container health check now closes it. The backend image no longer ships pip, whose bundled copies of other packages a scan reported.

Added: releases now carry a signed build-provenance attestation for the SBOM documents (GitHub artifact attestations), attached as `voice-delegate.intoto.jsonl` and verifiable with `gh attestation verify`. It applies from the next published release. An overview diagram of the system components is added to `docs/architecture.md`, and Sentry is recorded as a possible later addition in `docs/future-extensions.md`.

Changed: the frontend build uses Node.js 26 (now an LTS line) in the image, CI and `engines`. Node is only used to build and test the frontend; the production image serves static files from nginx. The pnpm install in that image no longer depends on Corepack, which Node 25 and later do not bundle: the registry tarball is installed only if its SHA-512 matches.

Added: fast-check property tests in the frontend (`frontend/src/properties.test.ts`). They generate event sequences for the session lifecycle state machine and arbitrary URLs for the evidence-link filter. fast-check (MIT) is a development dependency only.

Changed: the remaining unpinned build inputs are pinned by hash. The frontend image gets pnpm through Corepack from the `packageManager` field, which now carries the release's SHA-512, and the development container base image is pinned by digest and covered by Dependabot.

Changed: CodeQL also scans pull requests, so every change is analysed before merge (OpenSSF Scorecard's SAST check measures this). CodeQL, the container scan and the supply-chain audit cancel an older run when a newer commit arrives on the same branch.

Added: a nightly results workflow and page (`docs/results.md`). It runs the test suite with coverage, the load test and the offline worker evaluation, shows the numbers in the run summary and builds a static page with a 90-run history. Publishing to GitHub Pages is off until the owner enables Pages and sets `PUBLISH_RESULTS`.

Added: `.editorconfig` describing the conventions the repository already follows, a whitespace check (`scripts/check_editorconfig.py`) and a forbidden-files check (`scripts/check_forbidden_files.py`, the rule against committing `.env*`, keys and credentials) that run in every CI build, and a `.pre-commit-config.yaml` of local hooks (independence check, forbidden files, whitespace, ruff, mypy) for the optional pre-commit framework.

Added: container checks. A static audit of the Dockerfiles and compose files (pinned bases, non-root user, `HEALTHCHECK`, hardened services) runs in every CI build, and a Trivy workflow scans the built backend and frontend images weekly and when a container definition changes.

Fixed: the frontend image now defines a `HEALTHCHECK`; the audit found it was the only image without one.

Added: mutation testing of the limits and admission code (`make mutation`, weekly workflow). It raised the score from 72.7% to roughly 88-90% by exposing untested authentication, boundary and error-shape behaviour; new tests pin those down. `mutmut` is in the optional `mutation` dependency group.

Added: supply-chain checks (`docs/supply-chain.md`): a weekly and lockfile-triggered `pip-audit` and `pnpm audit`, CycloneDX SBOMs for the Python and frontend runtime dependencies attached to each release, and an OpenSSF Scorecard workflow. A test enforces that every workflow action is pinned to a commit and every workflow declares its permissions.

Added: contract fuzzing of the HTTP API with Schemathesis and property-based tests (Hypothesis) of admission, quotas and the rate limiter, run with the normal test suite (`docs/testing.md`). Both are development dependencies.

Fixed: the generated OpenAPI document now describes the API's real error answers. Every error body is `{"detail": "<message>"}`, but the document claimed the framework's list-shaped 422 and omitted the 400, 401, 403, 404, 409, 413, 429 and 503 responses. Runtime behaviour is unchanged.

Added: a Locust load test (`make loadtest`, `docs/load-testing.md`) that drives an isolated offline backend with many concurrent sessions and fails on error or latency budgets; it uses no provider, key or paid service. Locust and its dependencies are in the optional `loadtest` dependency group and are not part of the backend.

Added: a full live worker evaluation (40 cases, GPT-6 Luna with an LLM judge, 117 model calls) is published as a public Braintrust experiment: 98% judged correct, 99% grounded, 100% numeric and evidence retrieval, p50 2.4 s per case. Fixed: the eval scorers accept a typographic minus sign and curly apostrophes, which had marked correct answers as wrong. Per-case worker usage no longer includes the judge's call (reported as `judge_calls`), and skipped cases are no longer uploaded with timing invented by the Braintrust SDK. The social preview card is refreshed, with its figures labelled as LLM-judged and their source recorded.

Added: `VOICE_UNLIMITED_INVITES` lists invitation names (the operator's own) that skip the daily session and voice-second allowances without drawing on the shared daily budget; concurrency and session length still apply.

Fixed: spoken cancellation now works with GPT-Live. Its user transcript arrives one word at a time, and each word discarded the pending decision; the classifier now waits for the utterance to settle (0.4 s) and decides once, and its default deadline is 3 seconds instead of 1. The voice prompt no longer lets the assistant claim it stopped work before confirmation. The worker receives today's date, so questions about today or yesterday resolve. ElevenLabs captions no longer show expressive audio tags such as `[happy]`. README: iOS and Android shells and the evaluation setup are listed. Production logs are JSON on stdout with the real level, so Railway no longer shows every restart as errors, and successful polling calls are no longer logged.

Fixed: the offline worker eval retrieves every expected source again, and CI now fails if a documentation case misses one. Braintrust experiments record the worker's own duration and model calls instead of the upload time.

Fixed: a private worker service without a platform OpenAI key no longer disables moderation for personal-key jobs that bring their own key; the moderation classifier uses its own decider, so `VOICE_MODERATION_TIMEOUT_SECONDS` is no longer cut short by the 1-second decider default. README: live dashboard link and a 0.4.0 screenshot.

## 0.4.0 - 2026-11-04

The worker gains an opt-in safety boundary and read-only MCP tools, the hosted backend can export telemetry, the page is easier for first-time visitors, and the largest modules are split by responsibility.

Added: an opt-in moderation boundary in the worker (`VOICE_MODERATION`, ADR 013). Goals and tool evidence are reviewed by origin before planning; injected instructions in documentation or web excerpts are quarantined, and classifier failure withholds evidence instead of allowing it. An opt-in read-only MCP client for the worker (`VOICE_MCP_SERVERS`, ADR 010): operator-allowlisted servers and tools, reviewed flat schemas, cached immutable catalogs, bounded calls and moderated, cited output. It requires moderation and adds no dependency.

Changed: Live voice, Offline example and Project documentation are three peer tabs instead of a tab and a dropdown; while the invitation field is empty, a hint points to the Offline example and to Your API keys; the billing note is one line under Start; the tabs fit phone widths down to 320px. The README opens with what is implemented and a system diagram; the roadmap is a status table, with the verification history moved to `docs/milestones/evidence-log.md`; the transport notes moved next to the frontend code.

Added: hosted telemetry with the standard OpenTelemetry variables. With `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS` set (as Grafana Cloud provides them), traces and metrics are exported without a collector; explicit `VOICE_OTEL_*` endpoints keep precedence. Two importable Grafana Cloud dashboards (`observability/grafana-cloud/`) cover connections, latency, errors, cost, worker outcomes and traces.

Internal: Azure recovery moved from the session manager to `session/recovery.py`; the browser session lifecycle is an explicit, unit-tested state machine (`lifecycle.ts`) with backend requests in `api.ts`, and the session start is split into named steps; the worker planners moved to `planners.py` and MCP data review to `mcp_review.py`. Behavior is unchanged.

Verified through offline backend and frontend tests and hosted CI. The maintainer reported short sessions with all three voice providers on the deployed backend on 2026-11-04, with telemetry arriving in Grafana Cloud; this is not the recorded live checklist. Moderation and MCP have no live acceptance yet.

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
