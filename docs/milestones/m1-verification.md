Historical record as of 2026-09-20; current status in [docs/roadmap.md](../roadmap.md).

# M1 verification

## Automated candidate checks

The candidate includes tests for admission capacity, session ownership, duplicate offers, heartbeat and absolute expiry, setup timeout, shutdown, provider errors, unavailable delegation, SDP request validation, body limits, wire mappings, queue overflow, and confirmed versus unconfirmed close.

The GitHub Actions workflow runs the same lint, types, tests, client build, and Python package build. It has been prepared locally; a remote workflow run requires a GitHub repository.

## Manual live gate

The current [nine-step live acceptance checklist](live-verification.md#live-smoke-test-checklist) is maintained separately from this historical record.

## Known verification boundaries

No real API call, microphone playback test, or hosted GitHub Actions execution has been performed for this candidate. Reflected sideband audio is discarded; it is not a playback measurement. Public documentation specifies the protocol, but account availability and runtime timing remain unverified until the live test.

## Monorepo verification — 2026-09-20

Passed locally: 22 offline Python tests, Ruff, strict mypy (23 Python source files), locked uv/pnpm installs, Python wheel/sdist build, React production build, TypeScript checks, one Vitest unit test, and three Playwright browser tests. The browser tests cover API-free scripted playback, stopping playback, and live-mode guidance without a key.

The default Playwright browser CDN download failed in this environment. Browser tests passed with Chromium 153 installed separately through `PLAYWRIGHT_CHROMIUM_EXECUTABLE`. Standard CI installs Chromium through Playwright. Docker build, hosted CI, cloud deployment, real voice playback and paid API access remain unverified. No release tag was created.
