# ADR 013: Origin-aware moderation boundary in the worker

Date: 2026-11-04
Status: accepted

## Context

The worker reads text from three kinds of source: the user's delegated goal, bundled
documentation and external evidence such as web excerpts. Evidence can contain
instructions addressed to an assistant. A user request that is phrased as an imperative is
ordinary input and must not be treated the same way. A classifier can estimate, not prove,
that text is safe.

## Decision

Introduce one `Moderator` contract in the agent package, so the worker can import it
without a dependency on the API. Each review carries an `Origin` (user, documentation, web,
MCP) and returns a typed `Verdict` with an action (allow, quarantine, refuse) and a fixed
`Reason`. A `Classifier` supplies two advisory probabilities, instruction-to-assistant and
unsuitable; `PolicyModerator` applies deterministic rules to them:

- User text is refused only when unsuitable. An instruction-like signal is ignored, so
  ordinary requests and the cancellation-intent logic are unaffected.
- Evidence is quarantined when it reads as instructions or is unsuitable.
- Oversize text, an exhausted per-job review budget, a timeout and any classifier fault never
  allow. Evidence is quarantined; a user goal is declined with a reason and the session is
  unaffected.

The worker reviews the goal before planning and every tool result except arithmetic before
the planner sees it. A quarantined result ends the job as incomplete, records no sources and
is never narrated. There is no automatic substitution of other evidence in this version.

The backend adapter `DecisionsClassifier` calls the existing Decisions client once per
review with both predicates. `VOICE_MODERATION` is a flag because the feature spends money
and has no credential of its own to key off; it also requires `OPENAI_API_KEY` on the worker
host and is disabled on a private worker that lacks one. Review budgets are per job, so jobs
cannot contaminate one another, and decision calls and tokens flow into the existing cost
estimate. Telemetry is a counter labelled with origin, action and reason; text is never
logged.

## Consequences

Disabled mode is unchanged. Enabled mode adds one classifier call for the goal and one per
documentation, web or MCP result, each bounded by a timeout. The hook is also the boundary
that any future tool registry must pass through: unknown tools are reviewed with the MCP
origin.

Offline tests inject instructions through documentation and a fake web search, and cover
classifier failure, oversize text, budget exhaustion and legitimate imperative requests.
They prove enforcement with scripted signals. Real classifier quality, false-positive rates
and live latency remain pending authorized evaluation. Raw transcript segments before they
become a goal are not yet reviewed.
