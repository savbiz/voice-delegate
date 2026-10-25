# Local development and PyCharm

Install Python 3.12, [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 24 and pnpm (`npm install -g pnpm@11.19.0`). These tools do not require an API subscription.

Open the **voice-delegate** directory in PyCharm: it must contain the root `pyproject.toml`, `uv.lock`, `frontend/` and `backend/`. Use the repository directory as the project root. If `uv` reports no pyproject.toml, you are in the wrong folder.

From that root, run:

```bash
uv sync --locked
cp .env.example .env
pnpm --dir frontend install --frozen-lockfile
```

Configure PyCharm's interpreter as an existing environment at `.venv/bin/python` (Windows: `.venv/Scripts/python.exe`). Mark `backend/src` as Sources Root. For a Python run configuration select module `uvicorn`, arguments `voice_delegate.api.app:create_app --factory --host 127.0.0.1 --port 8000`, and working directory equal to the repository root. Environment settings load from root `.env` through python-dotenv.

Two terminal tabs:

```bash
# Tab 1, repository root
uv run uvicorn voice_delegate.api.app:create_app --factory --reload --host 127.0.0.1 --port 8000
```

```bash
# Tab 2, repository root
pnpm --dir frontend dev
```

Open **http://localhost:5173** (use localhost, matching the allowed origin). The free simulated demo works even without the Python server. It requests no microphone and plays no generated speech. Live voice needs `OPENAI_API_KEY` in root `.env`, GPT-Live access, and billed provider usage. Restart Python after changing settings. A ChatGPT subscription does not supply a project API key.

The access-code field accepts a configured personal invitation, or a shared `VOICE_ACCESS_TOKEN` for private testing. Enter that gate value, never an OpenAI key. It stays in browser memory. Editing it updates credentials for new sessions and standalone requests; an active session keeps its original invitation until close; switching modes releases the current voice session.

## Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv build --all-packages
pnpm --dir frontend build
pnpm --dir frontend test
pnpm --dir frontend exec playwright install chromium
pnpm --dir frontend test:e2e
```

Dependency and browser installation require internet; Python tests use no network and browser tests use only a local static server. Do not commit `.env`, `.venv`, node_modules or IDE configuration. Keep both lockfiles committed.

If your environment already provides Chromium, `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/absolute/path/to/chromium pnpm --dir frontend test:e2e` can use it instead of downloading Playwright's browser. The default CI path uses Playwright's own installation.

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
