# ADR 003: Separate deterministic orchestration tests from model evaluation

Status: accepted for M1; scenario expansion planned for M4.

Context: paid network calls introduce variability and require credentials. A fake model's configured choices cannot establish the behavior of a real model.

Decision: use typed fake events, injected clocks, and in-process HTTP to test lifecycle and failure paths. Block IP sockets in pytest. Keep real voice, model delegation accuracy, and measured transport latency behind an explicit live verification gate.

Consequences: offline CI can verify deterministic timeout policy and cleanup. It cannot certify spoken quality, barge-in behavior, real p50/p95 latency, or Azure failover. No M1 release tag is created until the live smoke test is recorded.
