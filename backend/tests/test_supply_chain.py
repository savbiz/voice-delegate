"""Workflow hygiene and the SBOM checker, verified offline from the files in the repository."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from scripts.check_sbom import check, main

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def load(path: Path) -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load(path.read_text())
    return data


def triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the bare key `on` as the boolean True.
    value = workflow.get("on", workflow.get(True))
    return dict(value) if isinstance(value, dict) else dict.fromkeys(list(value or []))


def steps(workflow: dict[Any, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_third_party_actions_are_pinned_to_a_commit(path: Path) -> None:
    for step in steps(load(path)):
        reference = step.get("uses", "")
        if reference and not reference.startswith("./"):
            assert PINNED.match(reference), f"{path.name}: {reference} is not pinned to a SHA"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_workflow_sets_permissions_and_avoids_pull_request_target(path: Path) -> None:
    workflow = load(path)
    assert "permissions" in workflow, f"{path.name} relies on the default token permissions"
    assert "pull_request_target" not in triggers(workflow)


def test_pnpm_only_runs_inside_the_frontend_directory() -> None:
    for path in WORKFLOWS:
        workflow = load(path)
        for job in workflow["jobs"].values():
            default = job.get("defaults", {}).get("run", {}).get("working-directory", "")
            for step in job.get("steps", []):
                for line in str(step.get("run", "")).splitlines():
                    if re.search(r"\bpnpm (?!/)", line) and "pnpm/action-setup" not in line:
                        inside = default == "frontend" or "cd frontend" in line
                        assert inside, f"{path.name}: pnpm outside frontend/: {line.strip()}"


def test_supply_chain_audits_both_ecosystems_weekly_and_on_lockfile_changes() -> None:
    workflow = load(ROOT / ".github/workflows/supply-chain.yml")
    on = triggers(workflow)
    assert {"schedule", "workflow_dispatch", "pull_request"} <= set(on)
    assert "uv.lock" in on["pull_request"]["paths"]
    assert "frontend/pnpm-lock.yaml" in on["pull_request"]["paths"]
    commands = " ".join(str(step.get("run", "")) for step in steps(workflow))
    assert "pip-audit@" in commands, "pip-audit must be version-pinned"
    assert "pnpm audit" in commands
    assert "--locked" in commands, "audit the lock file, not a fresh resolution"


def test_sbom_workflow_attaches_both_documents_to_releases() -> None:
    workflow = load(ROOT / ".github/workflows/sbom.yml")
    assert "release" in triggers(workflow)
    commands = " ".join(str(step.get("run", "")) for step in steps(workflow))
    assert "cyclonedx1.5" in commands
    assert "pnpm sbom --sbom-format cyclonedx" in commands
    assert "gh release upload" in commands
    # Only the one job that uploads to the release may write.
    assert workflow["permissions"] == {"contents": "read"}


def test_scorecard_publishes_results_with_the_permissions_it_requires() -> None:
    workflow = load(ROOT / ".github/workflows/scorecard.yml")
    job = workflow["jobs"]["analysis"]
    assert workflow["permissions"] == "read-all"
    assert job["permissions"]["id-token"] == "write"
    assert job["permissions"]["security-events"] == "write"
    scorecard = next(s for s in job["steps"] if "scorecard-action" in s.get("uses", ""))
    assert scorecard["with"]["publish_results"] is True


def document(components: list[dict[str, str]], fmt: str = "CycloneDX") -> str:
    return json.dumps({"bomFormat": fmt, "specVersion": "1.5", "components": components})


def test_sbom_checker_accepts_a_real_document(tmp_path: Path) -> None:
    path = tmp_path / "ok.json"
    path.write_text(document([{"name": "fastapi", "version": "0.141.1"}]))
    assert "1 components" in check(path)
    assert main([str(path)]) == 0


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (document([{"name": "x", "version": "1"}], fmt="SPDX"), "not a CycloneDX"),
        (document([]), "no components"),
        (document([{"name": "x"}]), "without a name or version"),
    ],
)
def test_sbom_checker_rejects_bad_documents(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(content)
    with pytest.raises(ValueError, match=message):
        check(path)
    assert main([str(path)]) == 1


def test_sbom_checker_needs_a_file_argument_and_reports_missing_files(tmp_path: Path) -> None:
    assert main([]) == 2
    assert main([str(tmp_path / "missing.json")]) == 1
