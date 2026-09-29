# ADR 008: Same-host API ownership and a private worker

Status: accepted 2026-09-30

Context: provider connections are process-owned while worker execution can be isolated. Adding API processes does not make an in-memory WebRTC session transferable.

Decision: prefix session IDs with a fixed instance ID, route lifecycle requests to that owner through nginx, and run one uvicorn worker per API. Share a durable quota/feedback volume on the same Docker host. Authenticate the separate worker service with a bearer token; bound concurrent jobs, deadlines and the cancellation ledger. Poll results every 200 ms and keep cancellation tombstones to suppress delayed submissions.

Consequences: an owner crash loses its live conversations; other owners continue serving their sessions. The gateway never retries stateful requests on another owner. Worker jobs and tombstones are ephemeral, so restart does not provide durable exactly-once execution. Cross-host ownership, distributed quota storage and service TLS are outside this topology's guarantees.

See [deployment](../../deployment/README.md), [worker API](../api.md) and [production scope](../production.md).
