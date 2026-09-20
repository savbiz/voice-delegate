# ADR 005: Bounded worker execution with generation-based cancellation

Status: accepted for M2.

Context: awaiting a worker in the voice event reader would delay handling new speech and cleanup. Tasks can time out, be superseded, or return after cancellation. GPT-Live client delegation carries an ID/timestamp but no task text.

Decision: assemble a bounded goal/context from transcripts and start a separate asyncio task. Use a LangGraph model/tool loop, one active delegation per session, global capacity, bounded steps and duration. Invalidate the session generation before cancellation and check it before result transmission. Keep duplicate IDs for the finite session lifetime, capped at 64. Use local microphone onset plus transcript timestamps for interruption, with an explicit cancel control.

Consequences: cancellation does not undo already-sent results or external effects. Initial tools are read-only and computationally bounded. A cooperative worker stops promptly; a noncooperative extension retains capacity until completion. Speech detection is heuristic and must be measured with real microphones. Context truncation may lose needed facts, so the worker must request clarification instead of guessing. Offline scripted model tests prove control behavior, not model quality.

Source: [public Live delegation guide](https://developers.openai.com/api/docs/guides/live-delegation). Limits and cancellation semantics are application design choices.
