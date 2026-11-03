---
name: add-dependency
description: Add or update a Python or frontend dependency and record its licence in THIRD_PARTY_NOTICES.md. Use whenever a package, SDK, build tool or generated code is introduced or its version changes.
---

# Add a dependency

Treat generated code as third-party code. Every new dependency and its licence must be
recorded in `THIRD_PARTY_NOTICES.md`.

## Steps

1. Prefer the standard library or an existing dependency. Check the candidate's licence
   is compatible (permissive: MIT, BSD, Apache-2.0, ISC). Ask before adding a copyleft or
   unknown licence.
2. Python (repository root): `uv add <package>` in the right package or group, which updates
   `uv.lock`. Frontend (`cd frontend` only): `pnpm add <package>` with an exact or
   deliberately ranged version. Never run `pnpm` from the root.
3. Regenerate notices by following `scripts/licenses/README.md` (inventory with
   pip-licenses and `pnpm licenses list --long`, then `scripts/build_notices.py`).
   Review the diff for both versions and the legal text; never hand-edit upstream licence
   texts. Packages without a licence file need an entry in the supplements file with its
   retrieval source.
4. Run `uv run pytest backend/tests/test_notices.py`, then the `repo-checks` skill.
5. Mention the package, version and licence in the commit body. Keep the dependency in the
   same commit as the code that needs it.

## Notes

- No real provider calls in tests; vendor SDK additions must work with fakes.
- If the dependency is optional or only used for tests/evals, say so rather than implying
  it ships in the browser or backend container.
