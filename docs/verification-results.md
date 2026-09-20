# Candidate verification results

Date: 2026-09-20. Python 3.12.14; Node.js 24.19.0.

| Check | Result |
|---|---|
| Ruff lint | Passed |
| Ruff formatting | Passed |
| mypy strict | Passed, 22 source files |
| pytest, IP sockets disabled | 21 passed |
| TypeScript strict and Vite production build | Passed |
| Python source distribution and wheel build | Passed |
| Real provider call and microphone/speaker smoke test | Not run |
| Hosted GitHub Actions | Not run; workflow included |
| M1 release tag | Withheld pending live verification |

Tests use an injected fake provider, in-process ASGI, and mocked HTTP/WebSocket boundaries. See m1-verification.md for the remaining live gate.
