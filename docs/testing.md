# Testing beyond examples

The unit and end-to-end suites check cases someone thought of. These add checks that find the
cases nobody did. All of them run offline, with the fake provider and disabled sockets, as part
of `uv run pytest`.

## API contract fuzzing (Schemathesis)

`backend/tests/test_api_contract.py` reads the API's own OpenAPI document and has
[Schemathesis](https://schemathesis.readthedocs.io) generate edge-case requests for every
operation: oversized and malformed bodies, wrong types, boundary values, unknown properties.
Each response must match the documented status codes and body shape, and the API must never
fail with a server error (a 503 for a feature that is switched off is the one documented
exception).

The first run found a real mismatch: every error body is `{"detail": "<message>"}`, but the
generated schema documented FastAPI's default list-shaped 422 and none of the 401, 403, 404, 409,
413, 429 or 503 answers. The OpenAPI document now describes what the API returns
(`ERROR_RESPONSES` in `api/schemas.py`), and the test keeps it that way.

Two checks are deliberately off: Schemathesis's "schema-valid request rejected" and
"schema-violating request accepted". Pydantic coerces lax input on purpose (`0` for `false`) and
some schema-valid bodies fail business rules (for example a voice adapter that is not enabled),
so symmetry between schema and behaviour is not a contract of this API.

The run is deterministic (`derandomize`), uses a different client address per request so the
per-IP limiter does not hide routes, and takes a few seconds.

## Property-based tests (Hypothesis)

- `test_admission_properties.py` drives the real SQLite-backed admission through random
  sequences of reservations, releases, clock advances and lease expiries, under three
  configurations that each make a different limit the one that binds. After every step it
  compares the outcome with a small independent model written from the documented rules and
  checks that the stored counters respect every limit: active sessions, per-user concurrency, and
  the daily session, per-user second and global second budgets.
- `test_ratelimit_properties.py` checks the token bucket for any traffic pattern: a client never
  exceeds its burst plus refill, an idle client always regains its full burst, and one client
  cannot change another's budget.

To confirm that these tests can fail, deliberate bugs were introduced in the real code (an
off-by-one on capacity, on the per-user, daily and global limits, on lease expiry and on the
personal-session reserve; a missing burst cap; a doubled refill; a dropped unlimited-invitation
check). Every one is caught except a "+1 second of global slack", which is equivalent here
because each reservation is a multiple of 11 seconds.

## Mutation testing (mutmut)

Coverage says a line ran, not that a test would notice if the line were wrong. Mutation testing
makes small wrong changes to the code (flip `>=` to `>`, drop a check, edit an error message) and
runs the tests against each one. A change that no test notices is a *surviving mutant*: behaviour
nothing pins down.

```sh
make mutation                 # or: uv run --group mutation python scripts/mutation.py --min-score 85
```

It targets `limits/` (rate limiter, body limit, token and result clipping) and `admission/`
(authentication, quotas, leases), 707 mutants, and takes two to four minutes. The configuration
is `[tool.mutmut]` in `backend/pyproject.toml`; the weekly `mutation` workflow runs it and fails
below the minimum score.

### What it found

The first run scored **72.7%** (514 of 707 mutants detected) on code with high line coverage.
The survivors were not noise:

- `authenticate` did not test that a bare token without the `Bearer ` prefix is refused, that
  database invitations authenticate at all, or that an unknown token never falls back to the open
  local identity.
- The property test of admission drew one user four times in a day too rarely to exercise the
  per-user seconds cap, never asserted the refusal reason, never used the doubled reservation for
  Azure recovery, and rarely landed on a lease's exact expiry instant.
- `truncate` had no test at its exact token, byte and 100,000-character boundaries, and its
  multibyte test never actually split a character (the chosen emoji is a single token).
- The body-limit and rate-limit middlewares were not checked for the shape of their 413 and 429
  answers, and idle rate-limit buckets were never shown to be evicted.

Each of these was fixed with a test (`test_admission_rules.py`, `test_limits_boundaries.py`, a
sharper `test_admission_properties.py`). The score is now roughly **88-90%**; it varies by about a point between runs because mutmut sometimes mislabels a survivor as a crash.

### What the remaining survivors are

Most of the rest cannot be killed or are not worth killing: SQL keywords written in another case
(SQLite ignores case), the SQLite connection timeout, defaults of a private helper, log wording,
and `strict=None` or `last=None` where `None` and `False` behave the same. Chasing 100% would mean
asserting implementation trivia. The minimum is set to 85% to leave room for run-to-run noise, not
as a target.

mutmut occasionally reports a surviving mutant's test process as a crash (`crashed` in the
report). Those are counted as *not* detected, so the score errs low.
