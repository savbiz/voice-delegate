"""Exercise the guard with synthetic names, without copying the real policy."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import check_independence as guard


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    return tmp_path


def stage(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    subprocess.run(["git", "add", "--", name], cwd=root, check=True)
    return path


def test_guard_checks_tracked_content_case_insensitively_and_excludes_lockfiles(
    repository: Path,
) -> None:
    stage(repository, "README.md", "Unrelated Examplecorporation\nEXAMPLECORP product\n")
    stage(repository, "uv.lock", "examplecorp")
    stage(repository, "frontend/pnpm-lock.yaml", "examplecorp")
    (repository / "untracked.txt").write_text("examplecorp")
    assert guard.check(repository, ("examplecorp",)) == [
        "README.md:2: prohibited term (content withheld)"
    ]


def test_only_policy_literals_are_exempt(repository: Path) -> None:
    stage(
        repository,
        guard.GUARD_PATH,
        'FORBIDDEN_TERMS = (\n    "examplecorp", # examplecorp\n)\nOTHER = "examplecorp"\n',
    )
    assert guard.check(repository, ("examplecorp",)) == [
        f"{guard.GUARD_PATH}:2: prohibited term (content withheld)",
        f"{guard.GUARD_PATH}:4: prohibited term (content withheld)",
    ]


def test_staged_scan_cannot_be_bypassed_by_clean_working_copy(repository: Path) -> None:
    file = stage(repository, "notes.md", "examplecorp")
    file.write_text("Independent project")
    assert guard.check(repository, ("examplecorp",)) == []
    assert guard.check(repository, ("examplecorp",), staged=True)
    stage(repository, "notes.md", "Independent project")
    file.write_text("examplecorp")
    assert guard.check(repository, ("examplecorp",), staged=True) == []


def test_tracked_filenames_are_checked_without_echoing_them(repository: Path) -> None:
    stage(repository, "examplecorp.txt", "unrelated")
    failures = guard.check(repository, ("examplecorp",))
    assert len(failures) == 1
    assert "examplecorp" not in failures[0]


@pytest.mark.parametrize(
    ("day", "hour", "expected"),
    [(12, 8, False), (12, 9, True), (12, 17, True), (12, 18, False), (17, 12, False)],
)
def test_local_work_hours_boundaries(day: int, hour: int, expected: bool) -> None:
    assert guard.work_hours(datetime(2026, 10, day, hour, tzinfo=UTC)) is expected


def test_warning_is_advisory_and_violations_still_fail(
    repository: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(guard, "ROOT", repository)
    monkeypatch.setattr("sys.argv", ["check_independence.py", "--staged", "--warn-work-hours"])
    monkeypatch.setattr(guard, "work_hours", lambda _now: True)
    assert guard.main() == 0
    assert "Warning:" in capsys.readouterr().out
    monkeypatch.setattr(guard, "check", lambda *_args, **_kwargs: ["Synthetic violation"])
    assert guard.main() == 1


def test_optional_hook_scans_the_index_and_warns_without_being_installed() -> None:
    hook = guard.ROOT / "scripts/hooks/pre-commit"
    assert hook.stat().st_mode & 0o111
    assert "--staged --warn-work-hours" in hook.read_text()


def test_repository_satisfies_its_independence_policy() -> None:
    assert guard.check(guard.ROOT) == []
