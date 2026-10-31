# LangGraph delegated worker

`src/voice_delegate_agent/graph.py` compiles a reason → tool → reason graph. Each invocation has its own state and no checkpoint storage. The injectable planner chooses one local tool or produces a final result. `OfflinePlanner` is deterministic; `OpenAIPlanner` enables a separately configured text model. Tools are a finite arithmetic interpreter and `search_documentation`, which retrieves excerpts from the bundled evergreen documentation corpus. Neither can mutate external state.

FastAPI owns timeout, cancellation, deduplication and result token/byte budgets. The graph owns its step budget. Instructions are separated from untrusted task context. See [Worker usage and limits](../docs/worker.md).

`OfflinePlanner` accepts English commands: `calculate <expression>`, `docs <query>`,
`architecture`, `limits`, and `delegation`, plus bare arithmetic expressions.
Documentation retrieval uses [demo aliases (en, it)](src/voice_delegate_agent/data/aliases.json)
and [stop words](src/voice_delegate_agent/data/stopwords.json), loaded from bundled JSON data
at import. These retrieval hints do not add translated commands to the offline planner.

Search ranks excerpt text by sublinear term frequency, without a heading bonus.
Queries of three or more content terms require at least half their terms in the corpus,
so an incidental match does not manufacture evidence for an unrelated question. When only a document title or section heading matches,
it returns matching excerpts in document order, so `architecture` opens the architecture overview.

`DecisionsPlanner` is an optional worker mode: a shared `Decider` selects a tool,
final response or refusal using a bounded choice question. The text model generates
only final prose on the successful choice path. Tool arguments are built by server
code; ambiguous arithmetic requires clarification. Classification failure uses the
existing OpenAIPlanner; refusals do not. See [configuration and limits](../docs/worker.md#decisions-worker-planner)
and [offline comparison](../evals/README.md#planner-comparison). Offline fake results
verify the control flow, not model quality; live planner comparison is pending.
