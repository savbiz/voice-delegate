"""Load-test an isolated offline backend with Locust and enforce latency and error budgets.

The backend is started here with the scripted voice provider and the offline worker, on a
loopback port, in an empty working directory and with a scrubbed environment: no provider key,
no ``.env`` file and no outbound call can reach it. Nothing is billed.

    uv sync --locked --group loadtest
    uv run --group loadtest python scripts/loadtest.py --users 40 --run-time 30s
"""

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://localhost:5173"
AGGREGATED = "Aggregated"
DURATION = re.compile(r"^\d+(ms|s|m|h)?$")


@dataclass(frozen=True)
class Row:
    name: str
    requests: int
    failures: int
    p50_ms: float
    p95_ms: float
    p99_ms: float


@dataclass(frozen=True)
class Budget:
    """Pass/fail limits; defaults leave headroom for a shared CI runner."""

    p95_ms: float = 500.0
    result_p95_ms: float = 3000.0
    max_failure_ratio: float = 0.0
    min_requests: int = 100


def parse_stats(text: str) -> list[Row]:
    """Read the ``*_stats.csv`` file that Locust writes."""
    return [
        Row(
            name=record["Name"],
            requests=int(record["Request Count"]),
            failures=int(record["Failure Count"]),
            p50_ms=float(record["50%"]),
            p95_ms=float(record["95%"]),
            p99_ms=float(record["99%"]),
        )
        for record in csv.DictReader(io.StringIO(text))
    ]


def violations(rows: list[Row], budget: Budget) -> list[str]:
    """Return one sentence per broken budget; an empty list means the run passed."""
    total = next((row for row in rows if row.name == AGGREGATED), None)
    if total is None or total.requests < budget.min_requests:
        count = 0 if total is None else total.requests
        return [f"only {count} requests completed; at least {budget.min_requests} are required"]
    problems = []
    ratio = total.failures / total.requests
    if ratio > budget.max_failure_ratio:
        problems.append(f"failure ratio {ratio:.2%} exceeds {budget.max_failure_ratio:.2%}")
    for row in rows:
        if row.name == AGGREGATED or row.requests == 0:
            continue
        limit = budget.result_p95_ms if row.name == "delegation result" else budget.p95_ms
        if row.p95_ms > limit:
            problems.append(f"{row.name}: p95 {row.p95_ms:.0f} ms exceeds {limit:.0f} ms")
    return problems


def report(rows: list[Row]) -> str:
    lines = [
        f"{'endpoint':<20}{'requests':>10}{'failures':>10}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}"
    ]
    lines += [
        f"{row.name:<20}{row.requests:>10}{row.failures:>10}"
        f"{row.p50_ms:>9.0f}{row.p95_ms:>9.0f}{row.p99_ms:>9.0f}"
        for row in rows
    ]
    return "\n".join(lines)


def backend_environment(max_sessions: int) -> dict[str, str]:
    """A minimal environment: the offline demo factory also refuses provider keys."""
    environment = {key: os.environ[key] for key in ("PATH", "HOME", "LANG") if key in os.environ}
    environment.update(
        {
            "VOICE_OFFLINE_DEMO": "1",
            "VOICE_WORKER_MODE": "offline",
            "VOICE_ALLOWED_ORIGINS": json.dumps([ORIGIN]),
            "VOICE_ALLOWED_HOSTS": json.dumps(["127.0.0.1", "localhost"]),
            "VOICE_MAX_SESSIONS": str(max_sessions),
            # Each virtual user sends its own X-Forwarded-For so the per-IP limiter models many
            # clients instead of throttling the one machine that generates the load.
            "VOICE_TRUST_PROXY": "true",
        }
    )
    return environment


def wait_ready(base_url: str, process: subprocess.Popen[bytes], budget: float = 30) -> None:
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        if process.poll() is not None:
            message = f"Backend exited early with code {process.returncode}"
            raise SystemExit(message)
        try:
            if httpx.get(base_url + "/healthz", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    message = "Backend was not ready in time"
    raise SystemExit(message)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--users", type=int, default=40, help="concurrent virtual users")
    parser.add_argument("--spawn-rate", type=float, default=10, help="new users per second")
    parser.add_argument("--run-time", default="30s", help="Locust duration such as 30s or 2m")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--max-sessions", type=int, default=100, help="backend capacity (max 100)")
    parser.add_argument("--p95-ms", type=float, default=Budget.p95_ms)
    parser.add_argument("--result-p95-ms", type=float, default=Budget.result_p95_ms)
    parser.add_argument("--csv-prefix", default="", help="keep Locust CSV files under this prefix")
    options = parser.parse_args(argv)
    if not DURATION.match(options.run_time):
        parser.error("--run-time must look like 30, 30s, 2m or 1h")
    if not (1 <= options.users <= 1000 and 1 <= options.max_sessions <= 100):
        parser.error("--users must be 1-1000 and --max-sessions 1-100")
    return options


def locust_command(options: argparse.Namespace, base_url: str, prefix: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(ROOT / "loadtest/locustfile.py"),
        "--headless",
        "--only-summary",
        "--host",
        base_url,
        "-u",
        str(options.users),
        "-r",
        str(options.spawn_rate),
        "-t",
        options.run_time,
        "--csv",
        prefix,
    ]


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    base_url = f"http://127.0.0.1:{options.port}"
    budget = Budget(p95_ms=options.p95_ms, result_p95_ms=options.result_p95_ms)
    with tempfile.TemporaryDirectory(prefix="voice-loadtest-") as scratch:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "voice_delegate.scaling.scripted_app:create_demo_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(options.port),
                "--no-access-log",
            ],
            cwd=scratch,
            env=backend_environment(options.max_sessions),
        )
        try:
            wait_ready(base_url, server)
            prefix = options.csv_prefix or str(Path(scratch) / "run")
            environment = dict(os.environ, LOADTEST_ORIGIN=ORIGIN)
            # Locust exits non-zero for failed requests; the budget below is the verdict.
            subprocess.run(locust_command(options, base_url, prefix), check=False, env=environment)
            stats = Path(prefix + "_stats.csv")
            if not stats.exists():
                print("Locust wrote no statistics", file=sys.stderr)
                return 2
            rows = parse_stats(stats.read_text())
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
    print(report(rows))
    problems = violations(rows, budget)
    for problem in problems:
        print("FAIL:", problem, file=sys.stderr)
    if not problems:
        print("Load test passed; no provider or paid service was contacted.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
