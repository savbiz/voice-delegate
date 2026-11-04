"""Docs-only pull requests skip heavy CI jobs; anything ambiguous must run the full pipeline."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci_docs_only import MAX_PATHS, docs_only

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "paths",
    [
        ["docs/architecture.md"],
        ["docs/images/workspace.png", "README.md", "CHANGELOG.md"],
        ["frontend/README.md", "deployment/README.md", ".railway/README.md"],
        [".agents/skills/commit-item/SKILL.md", ".claude/skills/commit-item/SKILL.md"],
        [".github/pull_request_template.md", ".github/ISSUE_TEMPLATE/bug_report.yml"],
        ["AGENTS.md", "THIRD_PARTY_NOTICES.md", "SECURITY.md", "CONTRIBUTING.md"],
    ],
)
def test_documentation_only_changes_are_recognised(paths: list[str]) -> None:
    assert docs_only(paths)


@pytest.mark.parametrize(
    "paths",
    [
        [],
        ["docs/architecture.md", "backend/src/voice_delegate/config.py"],
        # Prompts are markdown that ships in the container: they are code.
        ["backend/src/voice_delegate/prompts/blocks/core.md"],
        ["agent/src/voice_delegate_agent/prompts/worker.md"],
        # Even a README is packaged data when it lives under src/.
        ["backend/src/voice_delegate/limits/data/README.md"],
        ["agent/src/voice_delegate_agent/README.md", "docs/architecture.md"],
        ["docs/architecture.md", "frontend/src/App.tsx"],
        [".github/workflows/ci.yml"],
        [".github/actions/backend/action.yml"],
        # A file moved out of code into docs lists its old path too.
        ["docs/moved.md", "backend/src/voice_delegate/moved.py"],
        ["README.md.bak"],
        ["scripts/licenses/container-tooling.md"],
        ["LICENSE"],
        [f"docs/{i}.md" for i in range(MAX_PATHS)],
    ],
)
def test_anything_else_runs_the_full_pipeline(paths: list[str]) -> None:
    assert not docs_only(paths)


def run(stdin: str) -> str:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci_docs_only.py")],
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_command_line_answers_true_or_false() -> None:
    assert run("docs/api.md\nREADME.md\n") == "true"
    assert run("docs/api.md\nbackend/src/x.py\n") == "false"
    assert run("") == "false"
