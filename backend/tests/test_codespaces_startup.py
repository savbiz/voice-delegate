"""Exercise daemon readiness, persistent origins and failure diagnostics without Docker."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("codespaces", [False, True])
@pytest.mark.parametrize("failure", ["none", "daemon", "compose"])
def test_startup_waits_persists_origins_and_reports_failures(
    tmp_path: Path, codespaces: bool, failure: str
) -> None:
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / "deployment/demo").mkdir(parents=True)
    script = tmp_path / ".devcontainer/start-demo.sh"
    shutil.copy(ROOT / ".devcontainer/start-demo.sh", script)
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text("""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$TEST_CALLS"
if [ "$1" = info ]; then
  count=$(cat "$TEST_COUNT" 2>/dev/null || echo 0)
  echo $((count+1)) > "$TEST_COUNT"
  [ "$TEST_FAILURE" != daemon ] && [ "$count" -ge 2 ]
elif [[ "$*" == *'up --build'* ]]; then
  [ "$TEST_FAILURE" != compose ]
else
  echo 'recent container logs'
fi
""")
    docker.chmod(0o755)
    sleep = binary / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "CODESPACE_NAME",
            "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN",
            "DEMO_ALLOWED_ORIGINS",
        }
    }
    env.update(
        PATH=str(binary) + os.pathsep + env["PATH"],
        TEST_CALLS=str(tmp_path / "calls"),
        TEST_COUNT=str(tmp_path / "count"),
        TEST_FAILURE=failure,
    )
    if codespaces:
        env.update(
            CODESPACE_NAME="test-space", GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN="app.github.dev"
        )
    result = subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True, check=False, timeout=10
    )
    calls = (tmp_path / "calls").read_text().splitlines()
    assert calls[:3] == ["info"] * 3
    assert "compose -f deployment/demo/compose.yaml ps" in result.stdout
    assert "compose -f deployment/demo/compose.yaml logs --tail 30" in result.stdout
    if failure == "daemon":
        assert result.returncode == 1
        assert calls == ["info"] * 120
        assert not (tmp_path / "deployment/demo/.env").exists()
        return
    persisted = (tmp_path / "deployment/demo/.env").read_text().strip().split("=", 1)[1].strip("'")
    expected = ["http://localhost:8080"]
    if codespaces:
        expected += ["https://localhost:8080", "https://test-space-8080.app.github.dev"]
    assert json.loads(persisted) == expected
    if failure == "compose":
        assert result.returncode == 1
        assert calls[-1].endswith("logs --tail 30")
        assert "recent container logs" in result.stderr
    else:
        assert result.returncode == 0
        assert f"Offline demo: {expected[-1]}" in result.stdout
