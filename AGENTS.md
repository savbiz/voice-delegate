# Repository rules

- Never reference the author's employer, its products, people, events, internal names,
  numbers or documents in code, comments, documentation, tests, fixtures or commit messages.
- Never create or switch a GitHub repository to public. Never run `gh repo create`
  without `--private`. The author makes visibility changes manually.
- Never stage or commit `.env*`, `*.pem`, `*.key`, or files whose names match
  `*secret*` or `*credential*`. List staged files before every commit and check this rule.
- Treat generated code as third-party code. Record every new dependency and its licence
  in `THIRD_PARTY_NOTICES.md`.
- Make one commit per numbered item. Run all checks after each commit and resolve failures
  before starting the next item:

  ```sh
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy
  uv run pytest
  ```

  From `frontend/` only (never run pnpm from the repository root):

  ```sh
  pnpm lint
  pnpm build
  pnpm test
  pnpm test:e2e
  ```

- Do not push. The author pushes manually.
