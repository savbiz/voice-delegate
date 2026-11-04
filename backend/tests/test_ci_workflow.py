"""The main ruleset requires fixed CI check names; renaming or dropping a job blocks every merge."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_CHECKS = ("backend (3.14)", "frontend")


def workflow(name: str) -> str:
    return (ROOT / ".github/workflows" / name).read_text()


def test_required_check_names_exist_as_plain_jobs() -> None:
    ci = workflow("ci.yml")
    for check in REQUIRED_CHECKS:
        assert f"\n    name: {check}\n" in ci
    # A matrix leg would vanish when excluded and leave its required check unreported.
    assert "matrix:" not in ci


def test_backend_checks_run_on_the_one_supported_python_for_every_event() -> None:
    ci = workflow("ci.yml")
    job = ci.split("  backend:\n", 1)[1].split("\n  frontend:", 1)[0]
    assert 'python: "3.14"' in job
    assert "github.event_name" not in job
    assert "backend-31" not in ci


def test_codeql_scans_pull_requests_and_cancels_superseded_runs() -> None:
    codeql = workflow("codeql.yml")
    triggers = codeql.split("\npermissions:", 1)[0]
    assert "pull_request:" in triggers
    assert "cancel-in-progress: true" in triggers
    assert "branches: [main]" in triggers
    assert "schedule:" in triggers
    assert "workflow_dispatch:" in triggers


def test_docs_only_skips_fail_open_and_never_use_path_filters() -> None:
    ci = workflow("ci.yml")
    triggers = ci.split("\npermissions:", 1)[0]
    # Workflow-level path filters leave required checks unreported, which blocks merges.
    assert "paths" not in triggers
    # Only an explicit "true" skips work; a failed detection runs everything.
    assert ci.count("needs.changes.outputs.docs_only != 'true'") == 2
    assert "needs.changes.outputs.docs_only == 'true'" not in ci
    frontend = ci.split("  frontend:\n", 1)[1].split("\n    runs-on:", 1)[0]
    assert "!cancelled()" in frontend
    backend = ci.split("  backend:\n", 1)[1].split("\n    runs-on:", 1)[0]
    assert "!cancelled()" in backend


def test_ci_does_not_run_twice_for_a_pull_request_branch() -> None:
    triggers = workflow("ci.yml").split("\npermissions:", 1)[0]
    assert 'branches: ["**"]' not in triggers
    assert "branches: [main]" in triggers
    assert 'tags: ["*"]' in triggers
    assert "\n  pull_request:" in triggers
