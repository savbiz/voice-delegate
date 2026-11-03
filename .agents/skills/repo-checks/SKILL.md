---
name: repo-checks
description: Run this repository's verification checks in the right directories. Use after any code change, before committing, or when asked to run, verify or check the project. Never runs pnpm from the repository root.
---

# Repository checks

Run backend checks from the repository root and frontend checks from `frontend/` only.
Never run `pnpm` from the repository root (a stray root `package.json` or lockfile may
exist untracked; leave it alone).

## Backend (repository root)

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## Frontend (`cd frontend` first)

```sh
pnpm lint
pnpm build
pnpm test
pnpm test:e2e
```

## Rules

- Run only the side that your change touches while iterating, but run **all** checks
  before a commit is considered done (`AGENTS.md` requires this after every commit).
- Fix failures before starting the next item. Do not skip, xfail or loosen a check to get
  green; report a failure with its output if you cannot fix it.
- Tests use fakes and disabled sockets. Never add a paid provider call to a test.
- For release-grade verification, `CONTRIBUTING.md` lists extra checks (coverage floor,
  deployment, links, reference corpus, container smoke). Run those when asked for a full
  pre-release pass.
- State plainly which checks ran and which did not.
