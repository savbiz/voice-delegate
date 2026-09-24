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

## Worker quality and Braintrust experiments

The versioned `data/worker-v2.json` contains 32 synthetic cases: 12 arithmetic,
12 documentation questions with manually selected expected source IDs, four missing-evidence
queries and four live-only correction/unsupported-request cases. It contains no user sessions.
The remaining cases exercise the actual graph and tools with the scripted offline planner.

Run the free local baseline from the repository root:

```bash
uv run python -m evals.worker_eval --output .local/evals/offline.json
```

This runs 28 cases and marks four as skipped, with no provider or Braintrust calls even if
keys are present. Offline latency is graph/tool execution time, not model or acoustic latency.
Do not compare scripted quality results to live-model quality. The existing pytest suite
checks the dataset and scorers offline on every CI run, including deliberately wrong answers,
fabricated sources, invalid citation indices and model call-budget exhaustion.

### Connect Braintrust

Create a Braintrust account on the Starter plan and obtain an API key in account settings.
Add `BRAINTRUST_API_KEY=...` to the repository root `.env` (never to frontend variables).
Install the separate evaluation dependency group; it is not a backend runtime dependency:

```bash
uv sync --group eval --locked
uv run --group eval python -m evals.worker_eval --upload --project voice-delegate \
  --output .local/evals/offline-braintrust.json
```

Only `--upload` creates an experiment. It sends the selected synthetic goals/context, expected
rubrics, generated outputs, source IDs, tool names, scores and bounded run metadata. It does
not instrument the application, read the feedback database, record audio or upload users'
transcripts. Git automatic metadata collection is disabled; the report explicitly records
commit and tracked-dirty status. Braintrust authentication and upload still require a real
account/key; a local report is preserved if upload fails. SDK flushing completes before the
command reports success. Cloud retention follows your Braintrust plan, independently of the
seven-day local feedback policy.

### Run a small paid experiment

First check that your OpenAI project can use the worker and judge models. This example runs
three representative cases with up to four worker calls and one judge call each:

```bash
uv run --group eval python -m evals.worker_eval \
  --mode openai --model gpt-4.1-mini --allow-paid --max-model-calls 15 \
  --case math-01 --case docs-05 --case language-01 \
  --judge-model gpt-4.1-mini --upload --project voice-delegate \
  --output .local/evals/live-smoke.json
```

Omit `--upload` for a local-only report. Omit `--judge-model` for deterministic scoring only.
A full 32-case run needs a maximum budget of 128 calls without the judge, or 160 with it.
The command validates the conservative upper bound before starting, disables model retries,
and enforces the call budget at each invocation. Worker calls allow at most 1,000 completion
tokens; judge calls allow at most 500. Each worker case has a 45-second timeout and judge HTTP
calls a 20-second timeout. These limits bound requests and output, not an exact dollar amount.
Token totals use reported provider usage; failed calls may lack usage, and `cost_usd` stays
null rather than inventing a price. Both worker and judge consume provider usage.

To compare models, repeat the same selected cases and judge with a different `--model` and
output filename, uploading to the same project. In Braintrust, compare the experiments and
inspect the model, dataset/corpus/prompt hashes, case IDs and score sample counts before
interpreting differences. Compare multiple trials to assess model variability. No universal
quality threshold is imposed before collecting and reviewing a live baseline.

### What scores mean

- `numeric_result`: last numeric value in the answer matches the expected result; a formatting
  heuristic, not a general mathematical proof or language-quality judge.
- `tool_selection`: expected tool was requested, not proof that every action was necessary.
- `valid_source_ids` and `citation_indices_valid`: structural checks; they do not prove claims
  are supported by evidence.
- `expected_evidence_retrieved`: at least one manually labeled source was retrieved.
- `missing_evidence_signal`: English missing-evidence phrasing heuristic plus a separate
  no-sources check. It does not establish semantic abstention for every language.
- `bounded_output`: evaluates the same 120-token/500-byte clipping used for narration.
- Optional `judge_correctness`, `judge_usefulness`, `judge_groundedness`: advisory scores using
  rubric and evidence. The judge may be wrong or biased, particularly when using the same
  model as the worker. Review examples manually before using scores as a release gate.

Failures and skipped cases are recorded explicitly. A worker/judge execution failure exits
nonzero; a completed but low-quality answer remains in the report with its actual scores.
An absent judge is never represented as a perfect semantic score. Voice pronunciation,
WebRTC latency, listening tests, interruption timing and Azure failover remain separate tests.

Integration follows the official [Braintrust experiment SDK guide](https://www.braintrust.dev/docs/evaluate/run-in-code).
