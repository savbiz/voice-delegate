# Local development and PyCharm

Install Python 3.12, [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 24 and pnpm (`npm install -g pnpm@11.19.0`). These tools do not require an API subscription.

Open the **voice-delegate** directory in PyCharm: it must contain the root `pyproject.toml`, `uv.lock`, `frontend/` and `backend/`. Do not open only the archive's parent directory. If `uv` reports no pyproject.toml, you are in the wrong folder.

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

The access-code field is only needed when `VOICE_ACCESS_TOKEN` is configured. Enter that gate value, never an OpenAI key. It stays in browser memory. Editing the code or switching modes releases the current voice session.

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

## Upgrade from the M1 archive

Extract the M2 archive into a **new directory**. Open its `voice-delegate/` folder in PyCharm and copy your existing untracked `.env` into it. Run `uv sync --locked` and `pnpm --dir frontend install --frozen-lockfile`, then restart both servers. Do not replace a working .env with .env.example. New M2 settings have safe offline defaults. See [M2](milestones/m2.md) for enabling the text model.

If you want to keep your existing Git checkout, first commit or stash your edits. From that checkout, fetch the extracted repository with `git fetch /absolute/path/to/new/voice-delegate main` and then `git merge --ff-only FETCH_HEAD`. If your history diverged, this deliberately stops without discarding edits; merge/rebase your local commits before proceeding. Fetch candidate tags separately with `git fetch /absolute/path/to/new/voice-delegate tag v0.1.0-m2-rc.1`.
