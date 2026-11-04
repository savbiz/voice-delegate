"""The container audit passes on the real definitions and demonstrably fails on bad ones."""

import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
audit = SimpleNamespace(**runpy.run_path(str(ROOT / "scripts/check_containers.py")))

DIGEST = "sha256:" + "a" * 64
GOOD = f"""\
FROM python:3.12-slim@{DIGEST} AS build
RUN pip install --no-cache-dir uv
FROM python:3.12-slim@{DIGEST}
COPY --from=build /app /app
RUN useradd --uid 10001 app
USER app
HEALTHCHECK --interval=30s CMD ["true"]
"""


def test_the_repository_container_definitions_pass_the_audit() -> None:
    assert audit.main() == 0


def test_a_well_formed_dockerfile_has_no_findings() -> None:
    assert audit.audit_dockerfile(GOOD) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (("USER app\n", ""), "never sets USER"),
        (("USER app", "USER root"), "runs as root"),
        (("USER app", "USER 0:0"), "runs as root"),
        (('HEALTHCHECK --interval=30s CMD ["true"]\n', ""), "no HEALTHCHECK"),
        (("HEALTHCHECK --interval=30s", "HEALTHCHECK NONE #"), "no HEALTHCHECK"),
        (("python:3.12-slim@" + DIGEST + "\nCOPY", "python:3.12-slim\nCOPY"), "not pinned"),
        (("RUN useradd", "ENV API_TOKEN=abc\nRUN useradd"), "secret-looking"),
        (("RUN useradd", "ADD https://x.example/a.tgz /a\nRUN useradd"), "remote URL"),
        (
            ("RUN useradd", "RUN curl -fsSL https://x.example/i.sh | sh\nRUN useradd"),
            "into a shell",
        ),
    ],
)
def test_each_violation_is_reported(change: tuple[str, str], expected: str) -> None:
    findings = audit.audit_dockerfile(GOOD.replace(*change))
    assert any(expected in finding for finding in findings), findings


def test_a_user_set_only_in_an_earlier_stage_does_not_protect_the_final_stage() -> None:
    text = GOOD.replace(
        "FROM python:3.12-slim@" + DIGEST + " AS build\n",
        "FROM python:3.12-slim@" + DIGEST + " AS build\nUSER app\n",
    )
    text = text.replace("USER app\nHEALTHCHECK", "HEALTHCHECK")
    assert any("never sets USER" in finding for finding in audit.audit_dockerfile(text))


def test_a_later_stage_may_reference_an_earlier_one_by_alias() -> None:
    text = f"FROM python@{DIGEST} AS base\nFROM base\nUSER 1000\nHEALTHCHECK CMD true\n"
    assert audit.audit_dockerfile(text) == []


def hardened(**overrides: Any) -> dict[str, Any]:
    service: dict[str, Any] = {
        "build": {"context": "."},
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "ports": ["127.0.0.1:8080:8080"],
    }
    service.update(overrides)
    return {"services": {"web": service}}


def test_a_hardened_compose_service_passes() -> None:
    assert audit.audit_compose(hardened()) == []
    assert audit.audit_compose(hardened(user="101:101")) == []


def test_the_user_is_checked_on_services_that_are_not_built_here_too() -> None:
    data = {"services": {"proxy": {"image": "nginx:1.27", "user": "0"}}}
    assert audit.audit_compose(data) == ["service proxy runs as root (user: 0)"]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"read_only": False}, "not read-only"),
        ({"cap_drop": []}, "drop all capabilities"),
        ({"security_opt": []}, "no-new-privileges"),
        ({"privileged": True}, "privileged"),
        ({"user": "root"}, "runs as root"),
        ({"user": "0"}, "runs as root"),
        ({"user": 0}, "runs as root"),
        ({"user": "0:101"}, "runs as root"),
        ({"user": "root:nginx"}, "runs as root"),
        ({"network_mode": "host"}, "host network"),
        ({"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]}, "Docker socket"),
        ({"ports": ["8080:8080"]}, "every interface"),
        ({"ports": ["0.0.0.0:8080:8080"]}, "every interface"),
    ],
)
def test_each_compose_violation_is_reported(overrides: dict[str, Any], expected: str) -> None:
    findings = audit.audit_compose(hardened(**overrides))
    assert any(expected in finding for finding in findings), findings


@pytest.mark.parametrize(
    ("reference", "pinned"),
    [
        ("grafana/grafana:11.6.0", True),
        ("registry.example:5000/team/app:1.2", True),
        (f"nginx:1.27@{DIGEST}", True),
        ("nginx", False),
        ("nginx:latest", False),
        ("registry.example:5000/team/app", False),
    ],
)
def test_compose_images_must_name_a_version(reference: str, pinned: bool) -> None:
    assert audit.pinned_image(reference) is pinned
