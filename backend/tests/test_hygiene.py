"""Repository hygiene tooling: forbidden files, whitespace rules and the pre-commit hooks."""

import json
import runpy
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
forbidden = SimpleNamespace(**runpy.run_path(str(ROOT / "scripts/check_forbidden_files.py")))
whitespace = SimpleNamespace(**runpy.run_path(str(ROOT / "scripts/check_editorconfig.py")))


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "frontend/.env.production",
        "deploy/server.pem",
        "KEY.PEM",
        "certs/private.key",
        "src/my_secret.py",
        "docs/Secrets.md",
        "config/credentials.json",
        "aws_credential_helper.sh",
    ],
)
def test_forbidden_paths_are_refused(path: str) -> None:
    assert forbidden.forbidden(path) is not None


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "frontend/.env.example",
        "config/local.env.template",
        "backend/src/voice_delegate/config.py",
        "docs/keyboard.md",  # contains "key" but is not a *.key file
        "README.md",
    ],
)
def test_ordinary_paths_are_allowed(path: str) -> None:
    assert forbidden.forbidden(path) is None


def test_the_forbidden_check_reports_each_offender_and_passes_clean_input(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert forbidden.main(["README.md", "src/app.py"]) == 0
    assert forbidden.main([".env", "src/app.py", "id.pem"]) == 1
    errors = capsys.readouterr().err
    assert ".env: matches .env*" in errors and "id.pem: matches *.pem" in errors
    assert "app.py" not in errors


def test_no_tracked_file_is_forbidden() -> None:
    assert forbidden.main(["--tracked"]) == 0


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("a.py", b"x = 1\n", []),
        ("a.py", b"", []),
        ("a.py", b"x = 1", ["no final newline"]),
        ("a.py", b"x = 1\r\n", ["CR line endings"]),
        ("a.py", b"x = 1 \n", ["line 1 has trailing whitespace"]),
        ("a.py", b"if x:\n\ty = 1\n", ["line 2 is indented with a tab"]),
        ("Makefile", b"all:\n\tcc x.c\n", []),
        ("a.bin", b"\0\x01\x02", []),
        ("a.txt", b"\xff\xfe not utf-8", []),
    ],
)
def test_whitespace_rules(name: str, data: bytes, expected: list[str]) -> None:
    problems = whitespace.check_text(name, data)
    assert len(problems) == len(expected)
    for fragment, problem in zip(expected, problems, strict=True):
        assert fragment in problem


def test_generated_and_vendored_files_are_exempt_but_source_is_not() -> None:
    for path in (
        "uv.lock",
        "THIRD_PARTY_NOTICES.md",
        "frontend/android/app/build.gradle",
        "frontend/ios/App/App/Info.plist",
        "backend/src/voice_delegate/limits/data/tokenizer.json",
        "backend/LICENSE",
    ):
        assert whitespace.exempt(path), path
    for path in ("backend/src/voice_delegate/config.py", "frontend/src/App.tsx", "README.md"):
        assert not whitespace.exempt(path), path


def test_the_repository_meets_its_own_whitespace_rules() -> None:
    assert whitespace.main(["--tracked"]) == 0


def test_a_violating_file_fails_the_whitespace_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.py"
    bad.write_bytes(b"x = 1 \r\n")
    assert whitespace.main([str(bad)]) == 1
    assert "trailing whitespace" in capsys.readouterr().err


def sections() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    current = ""
    for raw in (ROOT / ".editorconfig").read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            current = line.strip("[]")
            result[current] = {}
        else:
            key, _, value = line.partition("=")
            result.setdefault(current, {})[key.strip()] = value.strip()
    return result


def test_editorconfig_agrees_with_the_formatters() -> None:
    config = sections()
    assert config[""]["root"] == "true"
    assert config["*"]["end_of_line"] == "lf"
    assert config["*"]["insert_final_newline"] == "true"
    ruff = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["ruff"]["line-length"]
    prettier = json.loads((ROOT / "frontend/.prettierrc.json").read_text())["printWidth"]
    assert int(config["*.{py,toml}"]["max_line_length"]) == ruff == 100
    assert int(config["*.{ts,tsx,js,mjs,json,yml,yaml,css,html}"]["max_line_length"]) == prettier
    assert config["*.{py,toml}"]["indent_size"] == "4"
    assert config["Makefile"]["indent_style"] == "tab"


def hooks() -> list[dict[str, object]]:
    data = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    assert [repo["repo"] for repo in data["repos"]] == ["local"], "no third-party hook repos"
    return list(data["repos"][0]["hooks"])


def test_pre_commit_runs_the_independence_check_and_every_repository_check() -> None:
    by_id = {hook["id"]: hook for hook in hooks()}
    assert len(by_id) == len(hooks()), "hook ids must be unique"
    assert {
        "independence",
        "forbidden-files",
        "editorconfig",
        "ruff-check",
        "ruff-format",
        "mypy",
    } <= set(by_id)
    independence = str(by_id["independence"]["entry"])
    assert "check_independence.py --staged" in independence
    assert by_id["independence"]["always_run"] is True


def test_every_script_a_hook_runs_exists() -> None:
    for hook in hooks():
        for word in str(hook["entry"]).split():
            if word.startswith("scripts/"):
                assert (ROOT / word).is_file(), f"{hook['id']}: {word} is missing"


def test_contributing_explains_how_to_use_the_hooks() -> None:
    text = (ROOT / "CONTRIBUTING.md").read_text()
    assert "pre-commit install" in text and "core.hooksPath" in text
