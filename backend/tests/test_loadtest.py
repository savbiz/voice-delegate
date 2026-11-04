"""The load-test budget logic is checked offline; the Locust run itself needs a local server."""

import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
loadtest = SimpleNamespace(**runpy.run_path(str(ROOT / "scripts/loadtest.py")))


def row(name: str, requests: int, failures: int, p95: float) -> str:
    return f"POST,1.0,{name},{requests},{failures},5,{p95},{p95}\n"


def parsed(*lines: str) -> list[object]:
    text = "Type,Requests/s,Name,Request Count,Failure Count,50%,95%,99%\n" + "".join(lines)
    return loadtest.parse_stats(text)  # type: ignore[no-any-return]


RESULTS = row("delegation result", 50, 0, 210)


def test_healthy_run_passes() -> None:
    rows = parsed(row("heartbeat", 400, 0, 12), RESULTS, row("Aggregated", 450, 0, 12))
    assert loadtest.violations(rows, loadtest.Budget()) == []


def test_any_failure_breaks_the_default_budget() -> None:
    rows = parsed(row("heartbeat", 400, 1, 12), RESULTS, row("Aggregated", 450, 1, 12))
    assert "failure ratio" in loadtest.violations(rows, loadtest.Budget())[0]


def test_slow_endpoint_is_named() -> None:
    rows = parsed(row("create session", 400, 0, 900), RESULTS, row("Aggregated", 450, 0, 900))
    assert loadtest.violations(rows, loadtest.Budget()) == [
        "create session: p95 900 ms exceeds 500 ms"
    ]


def test_delegation_result_has_its_own_limit() -> None:
    rows = parsed(row("delegation result", 400, 0, 1800), row("Aggregated", 400, 0, 1800))
    assert loadtest.violations(rows, loadtest.Budget()) == []


def test_requests_without_a_completed_delegation_cannot_pass() -> None:
    # Plenty of creates and sheds, but no conversation ever reached its result.
    rows = parsed(row("create session", 400, 0, 12), row("Aggregated", 400, 0, 12))
    assert loadtest.violations(rows, loadtest.Budget()) == [
        "only 0 delegated results completed; at least 10 are required"
    ]
    few = parsed(row("delegation result", 9, 0, 210), row("Aggregated", 400, 0, 12))
    assert "only 9 delegated results" in loadtest.violations(few, loadtest.Budget())[0]


def test_too_few_requests_cannot_pass() -> None:
    rows = parsed(row("heartbeat", 3, 0, 1), row("Aggregated", 3, 0, 1))
    assert "only 3 requests" in loadtest.violations(rows, loadtest.Budget())[0]
    assert "only 0 requests" in loadtest.violations([], loadtest.Budget())[0]


def test_backend_environment_carries_no_provider_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("VOICE_OPENAI_API_KEY", "sk-test")
    environment = loadtest.backend_environment(50)
    assert not [key for key in environment if "KEY" in key or "TOKEN" in key]
    assert environment["VOICE_OFFLINE_DEMO"] == "1"
    assert environment["VOICE_MAX_SESSIONS"] == "50"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--run-time", "soon"],
        ["--users", "0"],
        ["--max-sessions", "101"],
        ["--spawn-rate", "0"],
        ["--run-time", "11m"],  # beyond the longest run the workflow timeout allows
        ["--users", "100", "--spawn-rate", "5", "--run-time", "25s"],  # ramp 20s + 10s needed
    ],
)
def test_invalid_arguments_are_rejected(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        loadtest.parse_args(arguments)


def test_locust_command_targets_only_the_started_backend() -> None:
    options = loadtest.parse_args(["--users", "5", "--run-time", "30s"])
    command = loadtest.locust_command(options, "http://127.0.0.1:18765", "x")
    assert command[command.index("--host") + 1] == "http://127.0.0.1:18765"
    assert "--headless" in command


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("30", 30), ("30s", 30), ("2m", 120), ("1h", 3600), ("500ms", 0.5)],
)
def test_durations_are_converted_to_seconds(text: str, seconds: float) -> None:
    assert loadtest.duration_seconds(text) == seconds


def test_an_unsupported_duration_is_an_error() -> None:
    with pytest.raises(ValueError, match="Unsupported duration"):
        loadtest.duration_seconds("soon")


def test_a_run_that_just_reaches_full_load_is_accepted() -> None:
    options = loadtest.parse_args(["--users", "100", "--spawn-rate", "5", "--run-time", "30s"])
    assert options.users == 100


def test_an_occupied_port_is_refused_before_anything_starts() -> None:
    loadtest.ensure_port_free(18765, in_use=lambda _: False)
    with pytest.raises(SystemExit, match="already in use"):
        loadtest.ensure_port_free(18765, in_use=lambda port: port == 18765)
