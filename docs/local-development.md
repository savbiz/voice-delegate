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
