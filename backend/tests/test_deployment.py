"""Deployment templates must render concrete, narrowly scoped browser policy."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("host", ["", "https://api.example", "api.example/path", "x; img-src *"])
def test_vercel_renderer_rejects_missing_or_unsafe_host(tmp_path: Path, host: str) -> None:
    output = tmp_path / "vercel.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/render_vercel.py"), "--output", str(output)],
        env={**os.environ, "API_HOST": host},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "API_HOST must be a hostname" in result.stderr
    assert not output.exists()


def test_vercel_renderer_sets_headers_for_every_route(tmp_path: Path) -> None:
    output = tmp_path / "vercel.json"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/render_vercel.py"), "--output", str(output)],
        env={**os.environ, "API_HOST": "api.example"},
        capture_output=True,
        text=True,
        check=True,
    )
    config = json.loads(output.read_text())
    assert config["headers"][0]["source"] == "/(.*)"
    headers = {item["key"]: item["value"] for item in config["headers"][0]["headers"]}
    assert headers == {
        "Content-Security-Policy": (
            "default-src 'self'; connect-src 'self' https://api.example; media-src 'self' blob:; "
            "img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
        ),
        "Permissions-Policy": "microphone=(self), camera=()",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
    assert "${" not in output.read_text()
