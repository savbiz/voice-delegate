# Architecture decision records

Each record states one decision, its context and its consequences. Records are amended in
place with a dated note rather than rewritten.

| ADR | Decision | Status |
|---|---|---|
| [001](001-live-client-delegation.md) | GPT-Live with client delegation behind a provider protocol | Accepted 2026-09-20; amended 2026-11-04 |
| [002](002-lifecycle-and-bounds.md) | Explicit lifecycle ownership and finite budgets | Accepted 2026-09-20 |
| [003](003-offline-verification.md) | Deterministic orchestration tests separate from model evaluation | Accepted 2026-09-20 |
| [004](004-split-frontend-backend.md) | Static React frontend and persistent Python backend | Accepted 2026-09-20 |
| [005](005-bounded-delegation.md) | Bounded worker execution with generation-based cancellation | Accepted 2026-09-20 |
| [006](006-fallback-history.md) | One fallback attempt with clamped text history | Accepted 2026-09-30 |
| [007](007-invitation-admission.md) | Invitations and conservative quota admission | Accepted 2026-09-30 |
| [008](008-private-worker-scaling.md) | Same-host API ownership and a private worker | Accepted 2026-09-30 |
| [009](009-cancellation-is-intent.md) | Cancellation is intent; speech pauses narration | Accepted 2026-10-24 |
| 010 | Reserved for the MCP trust model in [future extensions](../future-extensions.md#worker-as-an-mcp-client) | Not written |
| [011](011-read-only-web-search.md) | Read-only web search in the delegated worker | Accepted |
