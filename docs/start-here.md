# Start here: a five-minute reading path

For someone reviewing the repository. Each step says what to read and what it shows.

1. **The idea (1 minute).** The [system diagram](../README.md#system-design): the voice model
   has one tool, and a bounded worker does the slow work while the conversation continues.
2. **Boundaries (2 minutes).** [Architecture](architecture.md) says which part owns the
   microphone, the session, the provider connection and delegation, and why audio never passes
   through the API.
3. **Two decisions worth reading.** [ADR 005](decisions/005-bounded-delegation.md) (bounded
   work, cancellation by generation, so a late result is never spoken) and
   [ADR 009](decisions/009-cancellation-is-intent.md) (why speaking does not cancel work).
   The rest are in the [decision index](decisions/README.md).
4. **Four files that carry it.**
   - [`session/manager.py`](../backend/src/voice_delegate/session/manager.py): session
     ownership, capacity and recovery.
   - [`delegation/runner.py`](../backend/src/voice_delegate/delegation/runner.py): finite tasks
     and suppression of stale results.
   - [`graph.py`](../agent/src/voice_delegate_agent/graph.py): the LangGraph worker.
   - [`lifecycle.ts`](../frontend/src/realtime/lifecycle.ts): the browser session state machine.
5. **Evidence, not claims.** [Evaluations](../evals/README.md); the live dashboard and the
   table of what is not yet verified are in the README's [status](../README.md#status) section.
6. **Run it without keys.** `bash .devcontainer/start-demo.sh`, or the Offline example tab on
   the hosted page.

The [documentation index](README.md) lists everything else by task.
