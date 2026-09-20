# Reproducible offline evaluation

`uv run pytest evals backend/tests/test_failover.py backend/tests/test_delegation.py`
runs scripted controls, timeout/cancellation budgets, duplicate suppression, bounded
context, stale results, fallback ownership, and one-attempt recovery. The JSON fixtures
contain invented utterances and provider decisions. A non-delegation fixture supplies no
delegation event; it verifies orchestration, not the model's decision to delegate.

`pnpm --dir frontend test:e2e` additionally verifies peer replacement and cleanup in a
browser with fake WebRTC and API responses. There are no audio recordings or paid calls.
Backend tests disable network sockets. OTel checks use only in-memory readers/exporters.

Live validation remains separate: run the M2 checklist, then force a primary connection
failure during conversation and during delegation. Verify Azure speech, no stale narration,
resource cleanup and bounded history. Record browser, provider deployment, sample count,
failures, and p50/p95 from actual runs. Do not infer audio latency or model accuracy from
scripted fixture timings. No live p50/p95 benchmark has been collected for this candidate.
