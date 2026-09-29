"""Deployment configuration contains concrete, narrowly scoped browser policy."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_vercel_headers_and_install_command_are_ready_for_git_deployment() -> None:
    content = (ROOT / "frontend/vercel.json").read_text()
    config = json.loads(content)
    assert "${" not in content
    assert config["installCommand"] == "pnpm install --frozen-lockfile"
    assert config["headers"][0]["source"] == "/(.*)"
    headers = {item["key"]: item["value"] for item in config["headers"][0]["headers"]}
    assert headers == {
        "Content-Security-Policy": (
            "default-src 'self'; connect-src 'self' "
            "https://voice-delegate-api-production.up.railway.app; style-src 'self'; "
            "img-src 'self'; media-src 'self'; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'"
        ),
        "Permissions-Policy": "microphone=(self), camera=()",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
