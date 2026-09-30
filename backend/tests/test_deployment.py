"""Deployment configuration contains concrete, narrowly scoped browser policy."""

import json
import re
import shutil
from pathlib import Path

import pytest

from scripts.check_deployment import check

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


def test_platforms_share_storage_health_and_required_variables() -> None:
    railway = json.loads((ROOT / "railway.json").read_text())
    resources = json.loads((ROOT / "deployment/railway-requirements.json").read_text())
    render = (ROOT / "render.yaml").read_text()
    assert railway["build"] == {
        "builder": "DOCKERFILE",
        "dockerfilePath": "deployment/Dockerfile.backend",
    }
    assert railway["deploy"]["restartPolicyType"] == "ON_FAILURE"
    assert railway["deploy"]["healthcheckPath"] == "/healthz"
    health = re.search(r"healthCheckPath: (/\S+)", render)
    assert health is not None and health[1] == "/healthz"
    mount = re.search(r"mountPath: (/\S+)", render)
    assert mount is not None and mount[1] == resources["volumeMountPath"] == "/app/.local"
    assert set(re.findall(r"- key: (\w+)", render)) == set(resources["requiredVariables"])
    assert {
        "OPENAI_API_KEY",
        "VOICE_INVITE_TOKENS",
        "VOICE_TRUST_PROXY",
        "VOICE_TRUSTED_PROXY_HOPS",
        "VOICE_QUOTA_DATABASE",
        "VOICE_FEEDBACK_DATABASE",
    } <= set(resources["requiredVariables"])


def test_public_api_host_documentation() -> None:
    check(ROOT)


@pytest.mark.parametrize("guide", ["deployment/README.md", "frontend/README.md"])
def test_missing_api_host_fails_documentation_check(tmp_path: Path, guide: str) -> None:
    for name in ("frontend/vercel.json", "frontend/README.md", "deployment/README.md"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    (tmp_path / guide).write_text("No API host documented here.")
    with pytest.raises(ValueError, match="CSP API host missing"):
        check(tmp_path)
