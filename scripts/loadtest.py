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
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://localhost:5173"
AGGREGATED = "Aggregated"
DURATION = re.compile(r"^(\d+)(ms|s|m|h)?$")
UNIT_SECONDS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, None: 1, "": 1}
MAX_RUN_SECONDS = 600  # the manual workflow's 20-minute timeout covers setup plus this
FULL_LOAD_SECONDS = 10  # at least this long with every virtual user running
SHUTDOWN_ALLOWANCE_SECONDS = 120
RESULT_ROW = "delegation result"


def duration_seconds(text: str) -> float:
    """Seconds in a Locust duration such as 30, 30s, 2m or 1h."""
    match = DURATION.match(text)
    if match is None:
        message = f"Unsupported duration {text!r}"
        raise ValueError(message)
    return int(match[1]) * UNIT_SECONDS[match[2]]


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
    min_results: int = 10  # completed delegations: proof the session lifecycle ran end to end


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
    completed = next((row.requests for row in rows if row.name == RESULT_ROW), 0)
    if completed < budget.min_results:
        problems.append(
            f"only {completed} delegated results completed; "
            f"at least {budget.min_results} are required"
        )
    ratio = total.failures / total.requests
    if ratio > budget.max_failure_ratio:
        problems.append(f"failure ratio {ratio:.2%} exceeds {budget.max_failure_ratio:.2%}")
    for row in rows:
        if row.name == AGGREGATED or row.requests == 0:
            continue
        limit = budget.result_p95_ms if row.name == RESULT_ROW else budget.p95_ms
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


def port_in_use(port: int) -> bool:
    """True when something already accepts connections on the loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def ensure_port_free(port: int, in_use: Callable[[int], bool] = port_in_use) -> None:
    """Refuse to start when the port is taken, so a /healthz answer cannot be someone else's."""
    if in_use(port):
        message = f"Port {port} is already in use; choose another with --port"
        raise SystemExit(message)


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
    if options.spawn_rate <= 0:
        parser.error("--spawn-rate must be positive")
    run_seconds = duration_seconds(options.run_time)
    if run_seconds > MAX_RUN_SECONDS:
        parser.error(f"--run-time must be at most {MAX_RUN_SECONDS} seconds")
    ramp_seconds = math.ceil(options.users / options.spawn_rate)
    if run_seconds < ramp_seconds + FULL_LOAD_SECONDS:
        parser.error(
            f"--run-time {options.run_time} is too short: reaching {options.users} users at "
            f"{options.spawn_rate:g}/s takes {ramp_seconds}s, and at least {FULL_LOAD_SECONDS}s "
            "at full load is required"
        )
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
    ensure_port_free(options.port)
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
            stats = Path(prefix + "_stats.csv")
            # A reused prefix must never let an earlier run's statistics pass for this one.
            stats.unlink(missing_ok=True)
            environment = dict(os.environ, LOADTEST_ORIGIN=ORIGIN)
            timeout = duration_seconds(options.run_time) + SHUTDOWN_ALLOWANCE_SECONDS
            try:
                completed = subprocess.run(
                    locust_command(options, base_url, prefix),
                    check=False,
                    env=environment,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                print(f"FAIL: Locust did not finish within {timeout:.0f}s", file=sys.stderr)
                return 1
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
    if completed.returncode != 0:
        problems.append(f"Locust exited with code {completed.returncode}")
    for problem in problems:
        print("FAIL:", problem, file=sys.stderr)
    if not problems:
        print("Load test passed; no provider or paid service was contacted.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
