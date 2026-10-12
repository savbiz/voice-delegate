# Contributing

Open the repository folder. Use Python 3.12 or 3.13, uv, Node.js 24 and the declared pnpm version. Install with `uv sync --locked` and `pnpm --dir frontend install --frozen-lockfile`. Work in small reviewable commits; add regression tests for changed behavior and preserve public HTTP/provider contracts unless the change explicitly includes a migration.

## Required checks

```bash
uv run python scripts/check_independence.py
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov=voice_delegate --cov=voice_delegate_agent --cov-fail-under=85
uv run python scripts/check_deployment.py
uv run python scripts/check_links.py
uv run python scripts/build_reference.py --check
pnpm --dir frontend lint
pnpm --dir frontend build
pnpm --dir frontend test
pnpm --dir frontend test:e2e
uv build --all-packages
docker build -f deployment/Dockerfile.backend -t voice-delegate:ci .
uv run python scripts/smoke_container.py
```

CI runs backend checks on Python 3.12 and 3.13, container build/smoke on 3.12, tag/version checks on tag pushes, and a frontend check rejecting unresolved Vercel placeholders. Pytest also verifies generated configuration documentation.

Run pnpm only for `frontend/`. Backend tests disable IP sockets and use fakes; do not add paid provider calls to CI. Voice/Azure acceptance is recorded separately with real environment and measurements, never invented numbers. Regenerate the reference corpus after evergreen documentation changes; bump the evaluation dataset version whenever labels change.

## Secrets and security

Never commit `.env`, provider keys, invitations, session keys, private recordings or exported cloud settings. Use synthetic fixture data. Report vulnerabilities privately through [SECURITY.md](SECURITY.md).

## Architecture decisions

For a durable architectural choice, add the next numbered Markdown file under [docs/decisions](docs/decisions/). Include title, `Status: accepted YYYY-MM-DD` (or proposed until accepted), context, decision, consequences and supporting sources. Describe implemented behavior in present tense and identify unverified assumptions. Keep historical acceptance evidence under [docs/milestones](docs/milestones/) and current status in [docs/roadmap.md](docs/roadmap.md).


## Independence check and optional local hook

Both CI jobs run `scripts/check_independence.py`. It scans tracked files, excluding
`uv.lock` and `frontend/pnpm-lock.yaml`, for prohibited terms without echoing their content.
Matching is case-insensitive and uses whole terms to avoid unrelated substrings in
third-party author names. Only the string literals in the script's top-level
`FORBIDDEN_TERMS` declaration are exempt; comments and the rest of the script are checked.
The check covers the current snapshot, not Git history or untracked files.

To enable the optional pre-commit hook, run from the repository folder:

```sh
git config core.hooksPath scripts/hooks
```

This replaces any existing local hooks path. The hook requires uv and checks the exact
staged content, blocking a commit on a violation. It also prints a non-blocking reminder
when local time is Monday–Friday from 09:00 inclusive to 18:00 exclusive. The reminder
does not determine whether work is permitted. To restore Git's default hooks path, run
`git config --unset core.hooksPath` (or restore your previous path).
