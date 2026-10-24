# Rebuilding third-party notices

The root `THIRD_PARTY_NOTICES.md` includes the installed runtime dependencies and,
separately from any claim about what is shipped, development/build/test/evaluation tools.
It records package versions and reproduces licence and NOTICE texts. No application
runtime dependency is added by this process. The inventory tools are pip-licenses (MIT)
and pnpm (MIT); pip-licenses is run through uv's isolated tool environment.

From the repository root, install the locked Python environment and collect its inventory:

```sh
uv sync --locked --all-groups
uv tool run pip-licenses --python .venv/bin/python --format=json --with-authors --with-urls --with-license-file --with-notice-file --output-file /tmp/voice-python-licenses.json
uv tool run --with 'uv_build==0.12.17' pip-licenses --format=json --packages uv_build --with-license-file --with-notice-file --with-authors --output-file /tmp/voice-build-licenses.json
```

Run the frontend inventory from `frontend/` only:

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm licenses list --long --json > /tmp/voice-frontend-licenses.json
cd ..
```

If pnpm reports missing store indexes, use a fresh installation of the same package.json
and lockfile under `frontend/.license-inventory/`, then run the inventory there. Do not
use an error response as an inventory. The generator rejects it.

```sh
uv run python scripts/build_notices.py --python-inventory /tmp/voice-python-licenses.json --build-inventory /tmp/voice-build-licenses.json --frontend-inventory /tmp/voice-frontend-licenses.json
uv run pytest backend/tests/test_notices.py
```

Review changes to both versions and legal text. `supplements.json` preserves upstream
texts for packages which omit a licence file, including each retrieval source. These
texts were collected on 2026-10-12. Some sources expose only an unversioned licence;
review them again when updating those packages. Other packages carry their full licence
in their README. The generator also inspects every Python distribution licence/NOTICE
file, rather than relying on the single file selected by pip-licenses.

The build copies the root document to `frontend/public/third-party-notices.txt` and then
into `dist/`; the generated copy is ignored by Git. Playwright checks the served copy
against the source and checks React legal comments in the production JavaScript.
Vite 8's active Rolldown
output also explicitly preserves legal comments.
