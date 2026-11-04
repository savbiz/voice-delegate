# Load testing

A [Locust](https://locust.io) scenario drives the backend the way many browsers would, with
no provider, key or network service involved. It answers three questions: does the session
lifecycle stay correct under concurrency, how fast do the endpoints stay, and does the server
shed load cleanly when it is full.

## Run it

```sh
uv sync --locked --group loadtest
make loadtest                                   # 40 users for 30 seconds
uv run --group loadtest python scripts/loadtest.py --users 150 --spawn-rate 50 --run-time 30s
```

`scripts/loadtest.py` starts the backend itself (it refuses a port that is already in use, and a run
longer than ten minutes or too short to reach the requested users), runs the scenario headless and prints a table.
It exits non-zero when a budget is broken, so it can gate a pipeline. The GitHub workflow
`loadtest` runs the same command on demand (Actions, Run workflow); it is not part of every
pull request, to save Actions minutes.

## What is under test

The backend runs from `voice_delegate.scaling.scripted_app:create_demo_app`, the offline
entry point also used by the container smoke test. It uses a scripted voice provider (no
audio, no provider connection) and the offline worker (a calculator and the bundled
documentation, no model). The factory refuses to start if a provider key is present, and the
runner starts it in an empty directory with a minimal environment, so a developer's `.env`
cannot reach it. Everything is on `127.0.0.1`.

Each virtual user repeats one conversation: create a session, send the connect offer, poll
the heartbeat until the delegated result (`2 + 2`) has been spoken, send three more
heartbeats and close. The result time is reported as `delegation result`.

Every user sends its own `X-Forwarded-For` address and the backend runs with
`VOICE_TRUST_PROXY=true`. Without that, the per-IP rate limiter (20 requests per second,
burst 100) would throttle the one machine generating the load and the test would measure the
limiter instead of the application. The limiter itself is covered by unit tests.

## Budgets

| Check | Default | Option |
|---|---|---|
| Failed requests | 0 | fixed |
| p95 of each endpoint | 500 ms | `--p95-ms` |
| p95 of `delegation result` | 3000 ms | `--result-p95-ms` |
| Requests completed | at least 100 | fixed |
| Delegated results completed | at least 10 | fixed |

A `429` when creating a session is counted as `shed at capacity`, not as a failure: it is the
designed answer once `VOICE_MAX_SESSIONS` (at most 100) sessions are open.

## Reference results

One run on an Apple M2 laptop, Python 3.12, load generator and server on the same machine.
These show the shape of the system on one process; they are not a capacity claim and will
differ on other hardware.

| Run | Users | Requests | Failures | Create p95 | Heartbeat p95 | Result p50 / p95 | Shed |
|---|---|---|---|---|---|---|---|
| Default | 40 | 2,271 | 0 | 11 ms | 4 ms | 210 / 210 ms | 0 |
| Overload | 150 | 8,561 | 0 | 34 ms | 11 ms | 200 / 220 ms | 410 of 1,308 creates |

The roughly 200 ms result time is internal to the scripted stack; it contains no network
or model time. In the overload run no request failed; the 410 creates
beyond the 100-session limit were refused with 429 and the 898 sessions that were admitted
completed normally.

## What it does not show

- Real voice quality or latency: audio never flows. See [benchmarks](benchmarks.md) for how
  provider timing is measured.
- Model-backed worker behaviour: the offline worker is deterministic and fast.
- Multi-instance behaviour or a production network path. The runner deliberately starts only its
  own loopback backend and refuses a port that is already in use: a run against a hosted API would
  create real sessions there, and the scenario does not present the invitations, allowed origins or
  conversation rules of the Compose stacks.
