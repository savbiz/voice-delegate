# Contributing

Open the repository folder. Use Python 3.14, uv, Node.js 26 and the declared pnpm version. Install with `uv sync --locked` and `pnpm --dir frontend install --frozen-lockfile`. Work in small reviewable commits; add regression tests for changed behavior and preserve public HTTP/provider contracts unless the change explicitly includes a migration.

## Required checks

```bash
uv run python scripts/check_independence.py
uv run python scripts/check_forbidden_files.py --tracked
uv run python scripts/check_editorconfig.py --tracked
uv run python scripts/check_containers.py
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

CI runs backend checks and the container build/smoke on Python 3.14, tag/version checks on tag pushes, and a frontend check rejecting unresolved Vercel placeholders. Pytest also verifies generated configuration documentation.

Run pnpm only for `frontend/`. Backend tests disable IP sockets and use fakes; do not add paid provider calls to CI. Voice/Azure acceptance is recorded separately with real environment and measurements, never invented numbers. Regenerate the reference corpus after evergreen documentation changes; bump the evaluation dataset version whenever labels change.

## Secrets and security

Never commit `.env`, provider keys, invitations, session keys, private recordings or exported cloud settings. Use synthetic fixture data. Report vulnerabilities privately through [SECURITY.md](SECURITY.md).

## Conduct

Be respectful in issues, pull requests and discussions. The expectations and how to report a problem are in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Architecture decisions

For a durable architectural choice, add the next numbered Markdown file under [docs/decisions](docs/decisions/). Include title, `Status: accepted YYYY-MM-DD` (or proposed until accepted), context, decision, consequences and supporting sources. Describe implemented behavior in present tense and identify unverified assumptions. Keep historical acceptance evidence under [docs/milestones](docs/milestones/) and current status in [docs/roadmap.md](docs/roadmap.md).


## Agent skills

Reusable agent skills live in `.agents/skills/` (Codex and other agents) and are mirrored
byte for byte in `.claude/skills/` (Claude Code). Edit `.agents/skills/`, then copy the
changes with `rm -rf .claude/skills && cp -R .agents/skills .claude/skills`; a test fails if
they drift. Skills encode the rules in `AGENTS.md`; keep them generic, free of secrets and
within the independence rule.

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

For a fuller set of checks before each commit, use the [pre-commit](https://pre-commit.com)
framework with the repository's `.pre-commit-config.yaml`. It runs the independence check on the
staged snapshot, refuses environment files, keys and credentials, checks line endings and
whitespace against `.editorconfig`, and runs ruff and mypy. Every hook is a local command, so no
hook repository is fetched. The framework refuses to install while `core.hooksPath` is set, so
choose one of the two:

```sh
uv tool install pre-commit
git config --unset core.hooksPath   # if you enabled scripts/hooks above
pre-commit install
pre-commit run --all-files          # optional: check everything once
```
