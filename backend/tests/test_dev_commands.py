"""Repository launchers select the correct working directory without starting services."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_default_make_target_only_shows_help() -> None:
    """Default make must show instructions without starting either service."""
    result = subprocess.run(["make", "-s"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert "make be" in result.stdout
    assert "make fe" in result.stdout


def test_dev_launchers_use_repo_paths_and_explicit_frontend_api(tmp_path: Path) -> None:
    """Stub executables verify working directories and local API selection."""
    for executable in ("uv", "pnpm"):
        command = tmp_path / executable
        command.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$VITE_API_BASE_URL" "$@"\n')
        command.chmod(0o700)
    environment = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]}
    environment.pop("VITE_API_BASE_URL", None)
    backend = subprocess.run(
        ["make", "-s", "be"], cwd=ROOT, env=environment, capture_output=True, text=True, check=True
    )
    assert backend.stdout.splitlines()[0] == str(ROOT)
    assert "scripts/dev.py" in backend.stdout
    assert "be" in backend.stdout
    for extra, expected in (
        ([], ""),
        (["VITE_API_BASE_URL=https://example.org"], "https://example.org"),
    ):
        frontend = subprocess.run(
            ["make", "-s", "fe", *extra],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        assert frontend.stdout.splitlines() == [str(ROOT / "frontend"), expected, "dev"]


def test_generated_local_invitation_is_stable_private_and_accepted(tmp_path: Path) -> None:
    """Generated admission must be reusable, owner-only and valid for the backend."""
    from pydantic import SecretStr
    from voice_delegate.admission.policy import Admission
    from voice_delegate.config import Settings

    from scripts.dev import invitation

    first = invitation(tmp_path)
    assert len(first) == 43
    assert invitation(tmp_path) == first
    assert (tmp_path / ".local/dev-invite.txt").stat().st_mode & 0o777 == 0o600
    assert (
        Admission(Settings(invite_tokens={"local-dev": SecretStr(first)})).authenticate(
            "Bearer " + first
        )
        == "local-dev"
    )


def test_local_launcher_preserves_env_file_and_model_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local auth overrides must not replace model options or rewrite the private file."""
    from scripts.dev import backend_environment, invitation

    for name in list(os.environ):
        if name.startswith("VOICE_"):
            monkeypatch.delenv(name)
    config = tmp_path / ".env"
    original = "VOICE_ACCESS_TOKEN=existing-test-code\nVOICE_WORKER_MODE=offline\n"
    config.write_text(original)
    monkeypatch.setenv("VOICE_MODEL", "test-voice-model")
    environment = backend_environment(tmp_path)
    assert environment["VOICE_MODEL"] == "test-voice-model"
    assert json.loads(environment["VOICE_INVITE_TOKENS"]) == {"local-dev": invitation(tmp_path)}
    assert environment["VOICE_ACCESS_TOKEN"] == ""
    assert "http://127.0.0.1:5173" in json.loads(environment["VOICE_ALLOWED_ORIGINS"])
    assert config.read_text() == original


def test_local_launcher_refuses_public_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The local shortcut must not launch a production/public configuration."""
    from scripts.dev import backend_environment

    monkeypatch.setenv("VOICE_ENVIRONMENT", "production")
    with pytest.raises(ValueError):
        backend_environment(tmp_path)
