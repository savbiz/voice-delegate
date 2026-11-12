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
COMPOSITE_ACTIONS = sorted((ROOT / ".github/actions").glob("*/action.yml"))
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


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflows_run_on_commits_cancel_superseded_runs(path: Path) -> None:
    workflow = load(path)
    if not {"pull_request", "push"} & set(triggers(workflow)):
        pytest.skip("not triggered by commits")
    concurrency = workflow.get("concurrency")
    assert concurrency, f"{path.name}: a newer commit must cancel the older run"
    assert concurrency["cancel-in-progress"] is True
    # Per workflow and ref, so a pull request never cancels main and workflows stay independent.
    assert "github.workflow" in concurrency["group"]
    assert "github.ref" in concurrency["group"]


IMAGE_ECOSYSTEMS = {"docker", "docker-compose"}


def test_dependabot_groups_minor_and_patch_updates_and_leaves_majors_separate() -> None:
    config = load(ROOT / ".github/dependabot.yml")
    ecosystems = {entry["package-ecosystem"] for entry in config["updates"]}
    assert {"uv", "npm", "github-actions", "docker", "docker-compose"} <= ecosystems
    for entry in config["updates"]:
        ecosystem = entry["package-ecosystem"]
        # Package ecosystems carry most security fixes, so they are checked every week.
        expected = "weekly" if ecosystem in {"uv", "npm"} else "monthly"
        assert entry["schedule"]["interval"] == expected, ecosystem
        for name, group in entry["groups"].items():
            if ecosystem in IMAGE_ECOSYSTEMS:
                # Digest refreshes have no semver type, so image groups take every update and
                # majors are kept out by an ignore rule instead.
                assert "update-types" not in group, name
                ignored = {
                    (rule["dependency-name"], tuple(rule["update-types"]))
                    for rule in entry.get("ignore", [])
                }
                assert ("*", ("version-update:semver-major",)) in ignored, name
            else:
                # A major update inside a group would hide a breaking change in a routine batch.
                assert group["update-types"] == ["minor", "patch"], name


def test_dependabot_leaves_python_version_upgrades_to_a_manual_change() -> None:
    config = load(ROOT / ".github/dependabot.yml")
    docker = next(e for e in config["updates"] if e["package-ecosystem"] == "docker")
    rules = {r["dependency-name"]: r["update-types"] for r in docker["ignore"]}
    # test_python_version pins the image to the project's Python; a bump must change both.
    assert rules["python"] == ["version-update:semver-minor"]


@pytest.mark.parametrize("path", COMPOSITE_ACTIONS, ids=lambda p: p.parent.name)
def test_composite_actions_are_pinned_and_watched_by_dependabot(path: Path) -> None:
    action = load(path)
    for step in action["runs"]["steps"]:
        reference = step.get("uses", "")
        if reference and not reference.startswith("./"):
            assert PINNED.match(reference), f"{path.parent.name}: {reference} is not pinned"
    config = load(ROOT / ".github/dependabot.yml")
    watched = next(e for e in config["updates"] if e["package-ecosystem"] == "github-actions")
    # Dependabot only reads action.yml files in the directories it is told about.
    assert f"/.github/actions/{path.parent.name}" in watched["directories"]


def test_playwright_browsers_are_cached_between_runs() -> None:
    commands = steps(load(ROOT / ".github/workflows/ci.yml"))
    names = [step.get("uses", "") + step.get("run", "") for step in commands]
    cache = next(i for i, text in enumerate(names) if text.startswith("actions/cache@"))
    install = next(i for i, text in enumerate(names) if "playwright install" in text)
    assert cache < install, "restore the browser cache before installing"
    assert commands[cache]["with"]["path"] == "~/.cache/ms-playwright"


def test_backend_image_build_reuses_layers_but_the_vulnerability_scan_does_not() -> None:
    action = load(ROOT / ".github/actions/backend/action.yml")
    build = next(s for s in action["runs"]["steps"] if "build-push-action" in s.get("uses", ""))
    assert build["with"]["load"] is True
    assert build["with"]["cache-from"].startswith("type=gha")
    assert build["with"]["cache-to"].startswith("type=gha")
    # A cached layer would keep an old package set and hide newly published vulnerabilities.
    scan = (ROOT / ".github/workflows/container-scan.yml").read_text()
    assert "cache-from" not in scan and "build-push-action" not in scan


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


def test_release_documents_carry_a_signed_provenance_attestation() -> None:
    workflow = load(ROOT / ".github/workflows/sbom.yml")
    job = workflow["jobs"]["sbom"]
    # Signing needs the OIDC token and attestation storage, granted to this one job only.
    assert job["permissions"]["id-token"] == "write"
    assert job["permissions"]["attestations"] == "write"
    assert "id-token" not in workflow["permissions"]
    attest = next(s for s in job["steps"] if "attest-build-provenance" in s.get("uses", ""))
    assert attest["if"] == "github.event_name == 'release'"
    assert attest["with"]["subject-path"] == "sbom/*.cdx.json"
    upload = next(s for s in job["steps"] if "gh release upload" in s.get("run", ""))
    assert "voice-delegate.intoto.jsonl" in upload["run"]


def test_scorecard_publishes_results_with_the_permissions_it_requires() -> None:
    workflow = load(ROOT / ".github/workflows/scorecard.yml")
    job = workflow["jobs"]["analysis"]
    assert workflow["permissions"] == "read-all"
    assert job["permissions"]["id-token"] == "write"
    assert job["permissions"]["security-events"] == "write"
    scorecard = next(s for s in job["steps"] if "scorecard-action" in s.get("uses", ""))
    assert scorecard["with"]["publish_results"] is True


def document(
    components: list[dict[str, str]], fmt: str = "CycloneDX", spec: str | None = "1.5"
) -> str:
    data: dict[str, Any] = {"bomFormat": fmt, "components": components}
    if spec is not None:
        data["specVersion"] = spec
    return json.dumps(data)


def test_sbom_checker_accepts_a_real_document(tmp_path: Path) -> None:
    path = tmp_path / "ok.json"
    path.write_text(document([{"type": "library", "name": "fastapi", "version": "0.141.1"}]))
    assert "1 components" in check(path)
    assert main([str(path)]) == 0


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            document([{"type": "library", "name": "x", "version": "1"}], fmt="SPDX"),
            "not a CycloneDX",
        ),
        (document([{"type": "library", "name": "x", "version": "1"}], spec=None), "no specVersion"),
        (document([{"name": "x", "version": "1"}]), "without a type"),
        (document([]), "no components"),
        (document([{"type": "library", "name": "x"}]), "without a name or version"),
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


def test_container_scan_builds_and_scans_both_images_and_the_configuration() -> None:
    workflow = load(ROOT / ".github/workflows/container-scan.yml")
    include = workflow["jobs"]["image"]["strategy"]["matrix"]["include"]
    assert {entry["image"] for entry in include} == {"backend", "frontend"}
    for entry in include:
        assert (ROOT / entry["dockerfile"]).is_file()
    scans = [s for s in steps(workflow) if "trivy-action" in s.get("uses", "")]
    # A readable listing and the failing SARIF scan per image (one matrix job), plus the
    # configuration scan.
    assert len(scans) == 3
    listing, gate = scans[0]["with"], scans[1]["with"]
    assert listing["format"] == "table" and listing["exit-code"] == "0"
    # An unfixed vulnerability is not actionable, so it must not fail the build.
    assert gate["ignore-unfixed"] is True and gate["exit-code"] == "1"
    assert gate["limit-severities-for-sarif"] is True
    assert gate["severity"] == listing["severity"] == "HIGH,CRITICAL"
    # One Trivy version everywhere, so the listing and the gate can never disagree.
    assert len({s["with"]["version"] for s in scans}) == 1
    assert workflow["permissions"] == {"contents": "read"}
