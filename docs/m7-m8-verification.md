# M7–M8 candidate verification

Date: 2026-09-21. Candidate version: `0.2.0.dev1`.
These are local checks, not hosted CI or live provider acceptance.

| Check | Evidence |
|---|---|
| Python lint and formatting | Ruff passed; 81 files formatted |
| Python types | mypy passed; 50 source files |
| Python tests | 85 passed, including remote overload mapped to `busy` without retry |
| Dependency lock | Offline lock check passed |
| Python packaging | Both packages built as source distributions and wheels |
| Frontend types and production build | TypeScript and Vite passed |
| Frontend unit tests | 3 passed |
| Browser checks | 7 Playwright tests passed before the final version/badge update |
| Patch whitespace | `git diff --check` passed |

## Docker acceptance exercise

The user reran `scripts/scaling_smoke.py` locally and supplied the successful terminal
output on 2026-09-21 (Compose project `voice-scale-check-565a05`). This replaces the earlier
run that reported overload as generic failure.

| Check | Result |
|---|---|
| Simulated voice | Yes |
| Paid provider calls | 0 |
| Sessions | 24 |
| API owners exercised | `a`, `b` |
| Completed jobs | 12 |
| Jobs rejected at capacity | 12, reported as `busy` |
| Failed jobs | 0 |
| Synthetic orchestration p50 | 0.277 s |
| Synthetic orchestration p95 | 0.502 s |
| Owner crash isolation and restart | Passed |
| Temporary containers, quota volume and network cleanup | Completed |

The `busy` results demonstrate controlled backpressure rather than task failures.
Latency includes polling and a scripted voice provider; it does not measure acoustic
latency or model quality. The supplied output does not include an image digest or build
log, so it is evidence of the successful Docker exercise rather than immutable build
provenance. Real provider and hosted acceptance remain separate gates below.

## Release acceptance

Before a stable release, collect real microphone/speaker evidence, interruption and
multilingual listening results, Azure fallback evidence, and representative provider
latency. Verify the chosen HTTPS deployment, invitation isolation, spending controls
and rollback, then run hosted CI and record the demonstration. See [roadmap](roadmap.md),
[M7](m7.md) and [M8](m8.md) for the precise scope and remaining gates.

No M9 is required by this roadmap. Further features should follow demonstrated user needs;
the immediate next work is completing these acceptance checks and fixing their findings.
