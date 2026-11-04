# Supply-chain checks

What the repository does to know what it ships and whether that is safe. Everything here runs in
GitHub Actions; none of it needs a secret or a paid service.

| Check | Workflow | When | What it answers |
|---|---|---|---|
| Dependabot | `.github/dependabot.yml` | weekly | Which updates exist (Python, npm, GitHub Actions) |
| CodeQL | `codeql.yml` | on `main` and weekly | Does the code contain known vulnerability patterns |
| Dependency audit | `supply-chain.yml` | weekly, on demand, and on a lockfile change | Does a locked package have a published advisory |
| SBOM | `sbom.yml` | on each published release, or on demand | What exactly is in the release |
| OpenSSF Scorecard | `scorecard.yml` | weekly, on `main` and on branch-protection changes | How do the repository's practices compare with a public baseline |

## Dependency audit

`pip-audit` checks the packages pinned in `uv.lock` (runtime, development and evaluation tools)
against the Python Packaging Advisory Database. `pnpm audit` checks `frontend/pnpm-lock.yaml`
and fails at moderate severity or above. They report advisories that exist today, which is what
Dependabot does not: a package nobody has updated can still become vulnerable.

Run them locally:

```sh
uv export --locked --all-groups --no-emit-workspace --no-hashes --format requirements-txt \
  --output-file /tmp/requirements-audit.txt
uv tool run pip-audit@2.10.1 --requirement /tmp/requirements-audit.txt --no-deps --disable-pip
cd frontend && pnpm audit --audit-level moderate
```

When the audit fails, update the package (Dependabot usually has a pull request), or, if no fix
exists, record why the advisory does not apply before ignoring it.

## SBOM

Each release gets two CycloneDX documents, attached to the release page: the Python runtime
dependencies (`voice-delegate-python.cdx.json`, from `uv export`) and the production frontend
dependencies (`voice-delegate-frontend.cdx.json`, from `pnpm sbom`). They are built from the lock
files with the tools the project already uses, so they add no dependency. `scripts/check_sbom.py`
fails the job if a document is empty or malformed. The workflow can also be run by hand to get
them as an artifact.

## Scorecard

[OpenSSF Scorecard](https://github.com/ossf/scorecard) scores practices such as pinned
actions, minimal token permissions, dependency updates, a security policy and branch protection.
Findings appear under Security, Code scanning; the public result is at
`https://scorecard.dev/viewer/?uri=github.com/savbiz/voice-delegate` once the workflow has run on
`main`. Scorecard limits what its workflow may contain, so keep `scorecard.yml` to the documented
steps.

## Conventions the tests enforce

`backend/tests/test_supply_chain.py` reads every workflow and fails if an action is not pinned to
a commit SHA, a workflow does not declare its token permissions, `pull_request_target` is used, or
`pnpm` runs outside `frontend/`.
