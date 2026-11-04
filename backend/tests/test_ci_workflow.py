"""The main ruleset requires fixed CI check names; renaming or dropping a job blocks every merge."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_CHECKS = ("backend (3.12)", "backend (3.13)", "frontend")


def workflow(name: str) -> str:
    return (ROOT / ".github/workflows" / name).read_text()


def test_required_check_names_exist_as_plain_jobs() -> None:
    ci = workflow("ci.yml")
    for check in REQUIRED_CHECKS:
        assert f"\n    name: {check}\n" in ci
    # A matrix leg would vanish when excluded and leave its required check unreported.
    assert "matrix:" not in ci


def test_python_313_is_skipped_on_pull_requests_not_removed() -> None:
    ci = workflow("ci.yml")
    job = ci.split("  backend-313:\n", 1)[1].split("\n  frontend:", 1)[0]
    assert "if: github.event_name != 'pull_request'" in job


def test_codeql_does_not_scan_every_pull_request_push() -> None:
    codeql = workflow("codeql.yml")
    triggers = codeql.split("\npermissions:", 1)[0]
    assert "pull_request" not in triggers
    assert "branches: [main]" in triggers
    assert "schedule:" in triggers
    assert "workflow_dispatch:" in triggers
