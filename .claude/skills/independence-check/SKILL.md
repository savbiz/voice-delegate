---
name: independence-check
description: Run and interpret the repository independence check that scans tracked files for prohibited references. Use before commits, when writing docs, code, tests, fixtures or commit messages, and when the check fails.
---

# Independence check

The repository must never reference the author's employer, its products, people, events,
internal names, numbers or documents - in code, comments, docs, tests, fixtures or commit
messages.

```sh
uv run python scripts/check_independence.py
```

## Rules

- The script scans tracked files and prints locations without echoing matched content.
  Do not try to recover or repeat the prohibited terms in chat, code or messages.
- The only exempt content is the string literals of `FORBIDDEN_TERMS` in
  `scripts/check_independence.py`. Do not add other exemptions, edit comments in that file
  to mention terms, or read the list out loud.
- It checks the current snapshot, not history and not untracked files. Stage new files
  first (or commit) to include them, and also review commit messages yourself.
- On failure: rewrite the offending text generically (describe the technical behaviour,
  not a source), re-run, and mention only that a violation was fixed.
- Use neutral, self-contained examples and synthetic data when documenting behaviour.
- An optional hook is available with `git config core.hooksPath scripts/hooks`; do not
  change a user's hooks path without being asked.
