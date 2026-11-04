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
