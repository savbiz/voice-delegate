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


def test_healthy_run_passes() -> None:
    rows = parsed(row("heartbeat", 400, 0, 12), row("Aggregated", 400, 0, 12))
    assert loadtest.violations(rows, loadtest.Budget()) == []


def test_any_failure_breaks_the_default_budget() -> None:
    rows = parsed(row("heartbeat", 400, 1, 12), row("Aggregated", 400, 1, 12))
    assert "failure ratio" in loadtest.violations(rows, loadtest.Budget())[0]


def test_slow_endpoint_is_named() -> None:
    rows = parsed(row("create session", 400, 0, 900), row("Aggregated", 400, 0, 900))
    assert loadtest.violations(rows, loadtest.Budget()) == [
        "create session: p95 900 ms exceeds 500 ms"
    ]


def test_delegation_result_has_its_own_limit() -> None:
    rows = parsed(row("delegation result", 400, 0, 1800), row("Aggregated", 400, 0, 1800))
    assert loadtest.violations(rows, loadtest.Budget()) == []


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
    "arguments", [["--run-time", "soon"], ["--users", "0"], ["--max-sessions", "101"]]
)
def test_invalid_arguments_are_rejected(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        loadtest.parse_args(arguments)


def test_locust_command_targets_only_the_started_backend() -> None:
    options = loadtest.parse_args(["--users", "5", "--run-time", "10s"])
    command = loadtest.locust_command(options, "http://127.0.0.1:18765", "x")
    assert command[command.index("--host") + 1] == "http://127.0.0.1:18765"
    assert "--headless" in command
