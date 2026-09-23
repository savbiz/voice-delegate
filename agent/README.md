# LangGraph delegated worker

`src/voice_delegate_agent/graph.py` compiles a reason → tool → reason graph. Each invocation has its own state and no checkpoint storage. The injectable planner chooses one local tool or produces a final result. `OfflinePlanner` is deterministic; `OpenAIPlanner` enables a separately configured text model. Tools are a finite arithmetic interpreter and a small local project reference lookup. Neither can mutate external state.

FastAPI owns timeout, cancellation, deduplication and result token/byte budgets. The graph owns its step budget. Instructions are separated from untrusted task context. See [M2 usage and limits](../docs/milestones/m2.md).

`OfflinePlanner` accepts English commands: `calculate <expression>`, `docs <query>`,
`architecture`, `limits`, and `delegation`, plus bare arithmetic expressions.
Documentation retrieval uses [demo aliases (en, it)](src/voice_delegate_agent/data/aliases.json)
and [stop words](src/voice_delegate_agent/data/stopwords.json), loaded from bundled JSON data
at import. These retrieval hints do not add translated commands to the offline planner.
