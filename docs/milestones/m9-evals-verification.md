# Initial worker evaluation evidence

Date: 2026-09-21. Implementation candidate; not a voice-quality release claim.

The versioned synthetic dataset has 32 cases. Offline execution completed 28 and explicitly
skipped four requiring a real language model. Arithmetic results and structural source checks
passed. Expected documentation evidence was retrieved in 11 of 12 cases (91.7%); the miss is
retained in the baseline. Scripted answers are not evidence of natural-language model quality.

A first three-case OpenAI smoke run used eight model requests, including two successful AI
judge calls. One correction case timed out. The run also exposed a numeric scorer bug with
sentence-ending punctuation; a regression test was added and the scorer fixed.

A second run of `math-01`, `docs-05` and `language-01`, using `gpt-4.1-mini` for worker and judge,
completed all three cases without execution errors in nine requests. Numeric checks and
expected-evidence retrieval scored 1.0. Judge correctness/usefulness averaged 1.0, while
groundedness averaged 0.667. These advisory scores require manual review; using the same model
for worker and judge is not independent validation. No aggregate semantic pass is claimed.
The first timeout remains part of the evidence, rather than being erased by the successful run.

Reported usage in the successful run was 2,954 input and 197 output tokens across worker and
judge. No dollar cost is inferred. The run's worker-only p50 was 2.262 s and p95 2.806 s, with
only three samples; these are not representative latency estimates or audio measurements.

94 Python tests passed with network sockets disabled, along with Ruff lint/format and existing
strict mypy checks. Tests cover wrong numeric results, fabricated evidence, invalid citations,
budget enforcement, explicit paid/upload gates, offline skips and curated upload payloads.
The optional Braintrust SDK was installed and its interfaces checked; no cloud experiment was
created because `BRAINTRUST_API_KEY` was unavailable. Upload authentication and real dashboard
visibility still need verification after the user configures that key.

Local detailed reports are in `.local/evals/`, which is ignored by Git. The synthetic evaluation
dataset and runner are version-controlled. Neither the evaluation runner nor Braintrust is
connected to production session logging or the diagnostic feedback database.
