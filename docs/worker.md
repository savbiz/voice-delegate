# Delegated worker

The worker runs a bounded LangGraph loop with a calculator and `search_documentation`. The default offline planner is deterministic and makes no provider calls. Enable the paid planner only on the backend for natural-language tool selection.

## Natural-language worker with live voice

Retain your existing `.env` and add:

```dotenv
VOICE_WORKER_MODE=openai
VOICE_WORKER_MODEL=gpt-4.1-mini
VOICE_WORKER_MAX_STEPS=4
VOICE_DELEGATION_TIMEOUT_SECONDS=15
VOICE_DELEGATION_RESULT_TOKENS=120
```

Set a project-scoped `OPENAI_API_KEY` on the backend. Restart the backend after changing worker settings. The deployed backend is Railway; these settings never belong in Vercel build variables. The text worker and live voice are separate billed model calls. Worker mode defaults to `offline`; enabling `openai` without a key fails configuration validation.

Try “Calculate the total of 120 and 80 plus 22 percent” or “Explain the limits of this architecture”. The worker has a calculator and documentation search. It cannot browse, book trips, send messages, or inspect external data. The text model can choose and sequence tools, subject to the step budget. Results are passed as commentary, never appended as trusted instructions.

## Budgets

| Resource | Limit | Reason |
|---|---|---|
| Worker model steps | 4 by default, configurable 1–12 | Stop model/tool loops |
| Tools per model response | 1 | Keep execution and cancellation predictable |
| Worker duration | 15 seconds, configurable | Keep slow work finite |
| Delegated result | 120 o200k tokens by default, configurable 8–480 | Keep narration compact |
| Wire commentary | 500 UTF-8 bytes | Conservative independent guard for Live's documented 500-token append cap |
| Transcript context | 12 recent speaker segments, 2,048 o200k tokens | Bound retained context and prompt cost |
| Goal | Latest user segment, 512 o200k tokens | Bound dispatch input |
| Calculator | 160 characters, 40 AST nodes, finite results within ±1e12 | No code execution or expensive arithmetic |

Token clipping preserves valid Unicode and includes an ellipsis within the budget. The actual result must satisfy both token and byte budgets. o200k assets and their MIT license are bundled: first use of token counting works offline, without a tokenizer download. Transcript grouping is approximate, not a definitive turn detector. Corrections and incomplete transcripts can still require clarification. See [fallback and replay](decisions/006-fallback-history.md) for recovery semantics.

## Request and cancellation limits

`VOICE_MAX_DELEGATIONS_PER_SESSION` defaults to 8 (maximum 64). Duplicate IDs do not dispatch work again. Running work is bounded by session capacity; a noncooperative worker retains capacity until it finishes. Cancellation invalidates the generation before cancelling the task, preventing late results from being narrated after the interruption is registered. Provider delivery has its own two-second deadline.

Provider speech detection is authoritative. The local onset detector is a latency optimisation and is suppressed during measurable remote playback. See [architecture](architecture.md), [configuration](configuration.md), and [operations](operations.md).

## Decisions worker planner

`VOICE_WORKER_MODE=decisions` is an experimental paid alternative to `openai`;
`offline` remains the default. Set it only on the existing backend or private worker,
with `OPENAI_API_KEY`, then restart that process. No frontend variable is required.
This mode is independent of `VOICE_DECISIONS_CANCEL`, which remains disabled by default.
The voice model still knows only `delegate_task`.

Each graph step asks `gpt-6-luna` one named `choice` question built from the current
worker tool names/descriptions, plus `direct` and `refuse`. A selected tool returns
one server-built call. `direct` invokes the configured text model without registered
tools for final prose; unexpected final tool calls are rejected. An explicit refusal
or an API refusal produces a bounded decline without a second model call.

Decisions selects a finite label; it does not generate arbitrary tool arguments.
Calculation currently requires an explicit expression such as `calculate (120+80)*1.22`
or `18/3`. An ambiguous phrase, a natural-language calculation or an unsupported tool
argument schema asks for clarification. Documentation search uses the goal as a bounded
query. Future tools need a deterministic argument builder before they can execute.
The current `openai` mode remains available for natural-language argument generation.

The Decisions deadline reuses `VOICE_DECISIONS_TIMEOUT_SECONDS` (default one second).
The adapter caps input text at 32 KiB, the serialized request and response at 64 KiB,
questions at four and options per choice at 32. A worker reserves two options for
`direct`/`refuse`, leaving at most 30 tool names. Refused, missing, malformed or unknown
answers cannot become tool names. Timeouts and unavailable/malformed classifications
fall back once for that step to the existing OpenAIPlanner. That fallback can select
tool arguments as before; refusals never activate it. Cancellation propagates and
never starts fallback work. There are no automatic HTTP retries.

Text requests retain the existing 20-second timeout and 1,000-token output cap; final
prose is additionally bounded to 8 KiB before the normal narration clipping. Model
failure follows the existing worker-failure path. The graph step limit and outer task
timeout also apply across classification and fallback. No keys or task text are logged.

The shared `Decider` types live in the agent package; backend imports remain compatible.
The API and private worker use the same planner factory and own their clients through
shutdown. Predicate cancellation and choice planning use separate clients and lifetimes.
The [offline comparison](../evals/README.md#planner-comparison) exercises contracts and
local execution only. Real planner accuracy, latency and cost remain live pending.

Contract source: [OpenAI Decisions API reference](https://developers.openai.com/api/reference/resources/decisions/methods/create).
