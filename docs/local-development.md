# Local development and PyCharm

Install Python 3.12, [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 24 and pnpm (`npm install -g pnpm@11.19.0`). These tools do not require an API subscription.

Open the **voice-delegate** directory in PyCharm: it must contain the root `pyproject.toml`, `uv.lock`, `frontend/` and `backend/`. Use the repository directory as the project root. If `uv` reports no pyproject.toml, you are in the wrong folder.

From that root, run:

```bash
uv sync --locked
if [ ! -e .env ]; then cp .env.example .env; fi
cd frontend
pnpm install --frozen-lockfile
cd ..
```

Configure PyCharm's interpreter as an existing environment at `.venv/bin/python` (Windows: `.venv/Scripts/python.exe`). Mark `backend/src` as Sources Root. For a Python run configuration select module `uvicorn`, arguments `voice_delegate.api.app:create_app --factory --host 127.0.0.1 --port 8000`, and working directory equal to the repository root. Environment settings load from root `.env` through python-dotenv.

Two terminal tabs:

```bash
# Tab 1, repository root
make be
```

```bash
# Tab 2, repository root
make fe
```

The repository [Makefile](../Makefile) provides these shortcuts without installing
shell aliases. Run `make` for help; it does not start a server. `make be` starts only
FastAPI with reload on `127.0.0.1:8000`; `make fe` starts only Vite on
`127.0.0.1:5173`. Stop each process with Ctrl+C. Dependencies must already be installed.

Run `make invite` to print a reusable **local** invitation, then paste it in the UI.
`make be` uses the same code, stored in ignored `.local/dev-invite.txt` with owner-only
permissions. Restart an existing backend with `make be` before using this code.
The launcher binds only to loopback and requires development mode with public demo
disabled. For that process only, it replaces configured invitation/shared-token auth
with the generated local invitation; the original `.env` is never rewritten and
its existing codes are never printed. Direct uvicorn startup still uses `.env` auth.
The local launcher permits both localhost and 127.0.0.1 frontend origins. `make invite`
is an explicit credential-display action; normal startup only prints the command to
retrieve it. Do not use this local code for Railway or invitations to hosted users.

Backend settings load from the existing root `.env`; process environment values take
precedence. Normal startup does not print API keys or configured invite codes. Only `make invite`
prints the generated local code when explicitly requested.
With no overrides, the adapter is `live`. A configured OpenAI key selects the model-backed
worker; without one, planning is offline. A Tavily key enables search. Runtime feature
flags for costs, controls, timing and intent cancellation are no longer required. See [all configuration names](configuration.md).

For one invocation, set options before the command:

```sh
VOICE_WORKER_MODE=openai make be
VOICE_WORKER_MODE=decisions make be
```

These model-backed modes require a privately configured `OPENAI_API_KEY` and can
incur provider charges. [Worker setup](worker.md) explains each mode. For persistent
choices edit your local `.env`, then restart the backend. Never put API keys in the
Makefile or frontend variables.

The frontend shortcut explicitly defaults `VITE_API_BASE_URL` to empty so Vite proxies
`/api` to the local backend, even if a frontend env file names a hosted API. To select
a hosted backend explicitly:

```sh
make fe VITE_API_BASE_URL=https://your-api.example
```

A non-local backend must allow the frontend origin. This does not deploy or modify
that backend. Paths are derived from the Makefile location, so linked worktrees use
their own backend and frontend directories.

Open **http://localhost:5173** (use localhost, matching the allowed origin). The free simulated demo works even without the Python server. It requests no microphone and plays no generated speech. Live voice needs `OPENAI_API_KEY` in root `.env`, GPT-Live access, and billed provider usage. Restart Python after changing settings. A ChatGPT subscription does not supply a project API key.

The access-code field accepts a configured personal invitation, or a shared `VOICE_ACCESS_TOKEN` for private testing. Enter that gate value, never an OpenAI key. It stays in browser memory. Editing it updates credentials for new sessions and standalone requests; an active session keeps its original invitation until close; switching modes releases the current voice session.

## Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv build --all-packages
cd frontend
pnpm lint
pnpm build
pnpm test
pnpm exec playwright install chromium
pnpm test:e2e
```

Dependency and browser installation require internet; Python tests use no network and browser tests use only a local static server. Do not commit `.env`, `.venv`, node_modules or IDE configuration. Keep both lockfiles committed.

If your environment already provides Chromium, `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/absolute/path/to/chromium pnpm test:e2e` from `frontend/` can use it instead of downloading Playwright's browser. The default CI path uses Playwright's own installation.

Container and same-host scaling checks are recorded in [Docker verification](milestones/m7-m8-verification.md#docker-acceptance-exercise). They exercise authentication, quotas and simulated orchestration without paid voice calls.

## Codespaces and Dev Containers

Open the repository in GitHub Codespaces, or select **Reopen in Container** with a
Dev Containers editor. `.devcontainer/devcontainer.json` builds a development image,
installs Docker-in-Docker and starts the same [offline stack](../deployment/README.md#offline-stack-in-one-command).
No provider key or invitation is needed. Keep all forwarded ports **private**.
Open forwarded port 8080 for the app, 3000 for Grafana and 9090 for Prometheus.

The post-start hook waits up to 120 seconds for Docker-in-Docker before starting
Compose. It runs after creation and after a stopped devcontainer is restarted.
If startup fails, it prints recent Compose logs and the inspection commands:

```sh
bash .devcontainer/start-demo.sh
docker compose -f deployment/demo/compose.yaml ps
docker compose -f deployment/demo/compose.yaml logs --tail 30
```

The script persists `DEMO_ALLOWED_ORIGINS` in ignored `deployment/demo/.env`, which
Compose reloads for subsequent commands with the same Compose file. No provider
credentials are written. Locally the list contains only `http://localhost:8080`.
In Codespaces it also contains `https://localhost:8080` and the public forwarded
origin derived from `CODESPACE_NAME` and `GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN`.
The backend uses `VOICE_ALLOWED_ORIGINS`; `VOICE_ALLOWED_ORIGIN` remains a deprecated
single-origin alias. An explicit list takes precedence over the alias.

### Measured Codespaces proxy behaviour

Hosted acceptance on 2026-10-25 found that the port-forwarding proxy rewrites
`Origin` to `https://localhost:8080` on requests to the page's own forwarded port,
and `Host` to `localhost:8080`. Requests to a different forwarded port retained
the original Origin. Setting the rewritten HTTPS origin allowed an offline
session, completed delegation and exported metrics. This is observed platform
behaviour, not a guarantee that the proxy will always rewrite headers.

To repeat the measurement, stop the frontend container, start a small HTTP echo
server on port 8080 that prints only `Origin` and `Host`, open its private forwarded
URL and send a same-origin fetch from the browser console. Compare a fetch from a
second private forwarded port. Do not print authorization or cookie headers. Stop
the echo server before restarting the stack. nginx still passes `Host: localhost`
to the backend; no allowed-host change is required.

For example, run this probe instead of the stopped frontend, then execute
`fetch('/probe', {method: 'POST'})` from its forwarded page's browser console:

```sh
docker compose -f deployment/demo/compose.yaml stop frontend
uv run python - <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer

class Echo(BaseHTTPRequestHandler):
    def do_GET(self):
        print({name: self.headers.get(name) for name in ("Origin", "Host")}, flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<title>Private origin probe</title>Origin probe")

    do_POST = do_GET

    def log_message(self, *args):
        pass

HTTPServer(("0.0.0.0", 8080), Echo).serve_forever()
PY
```

Stop the probe with Ctrl-C and run `bash .devcontainer/start-demo.sh` to restore
the frontend. For the cross-port comparison, forward another private echo-server
port and fetch the port-8080 URL from that page; a CORS error can occur after the
request reaches the probe, but the printed Origin remains useful evidence.

The offline demo populates operation duration, operations by outcome and
**Delegations by outcome**. Transcript wait, worker cancellations and browser
audio playback require live voice; an empty panel is expected offline.

The first build may take several minutes; the warm-cache goal excludes cold
provisioning. The reported run did not record creation/build timings or its commit.
If a measured cold start exceeds four minutes, enable a Codespaces prebuild in
repository Settings → Codespaces → Prebuilds, select this devcontainer and branch,
and rerun the timing from a newly created codespace. Prebuilds consume the account's
Codespaces allowance; check that allowance before enabling them. Keep ports private.

## Common local environment variables

The complete generated reference is [Configuration](configuration.md). Process
variables override `.env`; restart the backend after changes. Keep keys only in the
backend environment. Setting a key does not itself enable the corresponding feature.

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | OpenAI voice and, when selected, paid text/Decisions worker access. |
| `VOICE_ADAPTER` | Voice adapter: `live`, `realtime` or `azure`; default `live`. |
| `VOICE_MODEL` | GPT-Live model; applies to the `live` voice adapter. |
| `VOICE_REALTIME_MODEL` | Model used only by the OpenAI Realtime voice adapter. |
| `VOICE_VOICE` | Voice selection for the OpenAI voice adapters. |
| `VOICE_ACCESS_TOKEN` | Shared access code, used only when no named invitation map is configured. |
| `VOICE_INVITE_TOKENS` | JSON map of invitation names to individual codes; takes precedence over shared access. |
| `VOICE_ENVIRONMENT` | `development` for local work; production applies stricter host/origin/access requirements. |
| `VOICE_ALLOWED_ORIGINS` | JSON list of exact frontend origins permitted by routes, CORS and limiter responses. |
| `VOICE_ALLOWED_HOSTS` | JSON list of permitted backend Host names, separate from frontend origins. |
| `VOICE_PUBLIC_DEMO` | Enables named invitation/quota admission for a production public demo; false for local launcher. |
| `VOICE_INSTANCE_ID` | Instance prefix for same-host routing; leave empty for simple local use. |
| `VOICE_WORKER_EXECUTION` | `local` in-process worker or `remote` private worker service. |
| `VOICE_WORKER_MODE` | Planner choice: deterministic `offline`, text-model `openai`, or `decisions`. |
| `VOICE_WORKER_MODEL` | Text model for the model-backed worker, independent of the voice model. |
| `VOICE_OTEL_ENABLED` | Enables optional backend OpenTelemetry tracing; it does not enable transcript recording. |
| `VOICE_DEBUG_RECORDING` | Makes consent-based server debug recording available; a session must explicitly opt in. |
| `TAVILY_API_KEY` | Supplying this private worker key enables web search. |
| `BRAINTRUST_API_KEY` | Optional evaluation upload credential; unused by ordinary voice sessions. |

`make be` deliberately uses isolated local invitation auth while retaining model and
feature choices. Public-demo/production configurations must use the normal deployment
entry point; they are rejected by the local launcher. `make fe` uses an empty
`VITE_API_BASE_URL` by default to proxy to the local backend. Override that public URL
only when explicitly selecting a hosted API; it is not a place for credentials.

`VOICE_ADAPTER` is the canonical selector for the existing `live`, `realtime` and
`azure` adapters. It selects an integration, not the commercial provider. The old
`VOICE_VOICE_PROVIDER` name remains accepted as a deprecated alias; if both names
are present in the same source, `VOICE_ADAPTER` wins. Keep your existing keys and change only the
non-sensitive selectors/model values when migrating a local configuration.

## Copyable local configuration

Use the [minimal template](../config/local.env.template) for new files. It contains
platform keys and deployment choices; costs, controls, audio timing and intent-based
cancellation are automatic. Existing `.env` files still load, but obsolete feature flags
do not disable these behaviours. The older `.env.example` is a legacy exhaustive template.

For platform-funded local voice and model-backed delegation:

```dotenv
OPENAI_API_KEY=REPLACE_WITH_YOUR_KEY
TAVILY_API_KEY=REPLACE_WITH_YOUR_OPTIONAL_SEARCH_KEY
VOICE_ADAPTER=live
VOICE_WORKER_EXECUTION=local
```

Omit the Tavily line if unused; supplying a key enables its tool. Use `make be`, `make fe`
and `make invite`; keep the local invitation private. Your API keys mode instead accepts
keys per session and needs no invitation or platform provider keys. See
[personal-key access](personal-api.md). No environment file is rewritten automatically.

For a separately started private worker, set `VOICE_WORKER_EXECUTION=remote`,
`VOICE_WORKER_SERVICE_URL` and a shared `VOICE_WORKER_SERVICE_TOKEN`. Keep the same worker
model on both hosts; platform provider keys belong on the host that uses them. Personal
OpenAI/Tavily keys are forwarded only for that job and discarded when it ends.

Explicit `VOICE_WORKER_MODE=offline`, `openai` or `decisions` remains available. Resource
budgets, allowed origins/hosts, invitations, proxy trust and private-worker authentication
remain configurable. Debug recording, telemetry and paid semantic cancellation still
require deliberate setup; they are not enabled merely by supplying a voice key.

Restart the API and private worker after changing deployment settings. Browser API keys
are never read from `.env` and are not stored in the frontend build.
