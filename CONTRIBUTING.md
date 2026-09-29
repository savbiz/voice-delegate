# Contributing

Open the repository folder. Use Python 3.12 or 3.13, uv, Node.js 24 and the declared pnpm version. Install with `uv sync --locked` and `pnpm --dir frontend install --frozen-lockfile`. Work in small reviewable commits; add regression tests for changed behavior and preserve public HTTP/provider contracts unless the change explicitly includes a migration.

## Required checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov=voice_delegate --cov=voice_delegate_agent --cov-fail-under=85
uv run python scripts/check_links.py
uv run python scripts/build_reference.py --check
uv run python scripts/build_configuration.py --check
pnpm --dir frontend lint
pnpm --dir frontend build
pnpm --dir frontend test
pnpm --dir frontend test:e2e
uv build --all-packages
docker build -f deployment/Dockerfile.backend -t voice-delegate:ci .
uv run python scripts/smoke_container.py
```

Run pnpm only for `frontend/`. Backend tests disable IP sockets and use fakes; do not add paid provider calls to CI. Voice/Azure acceptance is recorded separately with real environment and measurements, never invented numbers. Regenerate the reference corpus after evergreen documentation changes; bump the evaluation dataset version whenever labels change.

## Secrets and security

Never commit `.env`, provider keys, invitations, session keys, private recordings or exported cloud settings. Use synthetic fixture data. Report vulnerabilities privately through [SECURITY.md](SECURITY.md).

## Architecture decisions

For a durable architectural choice, add the next numbered Markdown file under [docs/decisions](docs/decisions/). Include title, `Status: accepted YYYY-MM-DD` (or proposed until accepted), context, decision, consequences and supporting sources. Describe implemented behavior in present tense and identify unverified assumptions. Keep historical acceptance evidence under [docs/milestones](docs/milestones/) and current status in [docs/roadmap.md](docs/roadmap.md).
