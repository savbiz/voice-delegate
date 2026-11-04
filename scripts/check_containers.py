"""Audit the container definitions: pinned bases, non-root user, health check, hardened compose.

A pure-Python check with no Docker needed, so it runs on every pull request. Image vulnerability
scanning is a separate, heavier workflow (.github/workflows/container-scan.yml).

    python scripts/check_containers.py
"""

import re
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "deployment"
ROOT_USERS = {"root", "0", "0:0", "root:root", "0:root", "root:0"}
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.I)
PIPE_TO_SHELL = re.compile(r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z)?sh\b")


def instructions(text: str) -> list[tuple[str, str]]:
    """Dockerfile instructions as (KEYWORD, arguments), joining continuations, dropping comments."""
    joined = re.sub(r"\\\s*\n", " ", text)
    result = []
    for line in joined.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            keyword, _, arguments = stripped.partition(" ")
            result.append((keyword.upper(), arguments.strip()))
    return result


def audit_dockerfile(text: str) -> list[str]:
    """One sentence per violation; an empty list means the Dockerfile passes."""
    problems: list[str] = []
    parsed = instructions(text)
    stages: list[list[tuple[str, str]]] = []
    aliases: set[str] = set()
    for keyword, arguments in parsed:
        if keyword == "FROM":
            parts = arguments.split()
            image = next(part for part in parts if not part.startswith("--"))
            if image not in aliases and not DIGEST.search(image):
                problems.append(f"base image {image} is not pinned by sha256 digest")
            if "AS" in [part.upper() for part in parts]:
                aliases.add(parts[[part.upper() for part in parts].index("AS") + 1])
            stages.append([])
        if stages:
            stages[-1].append((keyword, arguments))
    if not stages:
        return ["no FROM instruction"]
    final = stages[-1]
    users = [arguments for keyword, arguments in final if keyword == "USER"]
    if not users:
        problems.append("the final stage never sets USER, so it runs as root")
    elif users[-1].strip().lower() in ROOT_USERS:
        problems.append(f"the final stage runs as root (USER {users[-1]})")
    checks = [arguments for keyword, arguments in final if keyword == "HEALTHCHECK"]
    if not checks or checks[-1].upper().startswith("NONE"):
        problems.append("the final stage defines no HEALTHCHECK")
    for keyword, arguments in parsed:
        if keyword == "ADD" and re.search(r"https?://", arguments):
            problems.append(f"ADD fetches a remote URL without verification: {arguments[:60]}")
        if keyword == "RUN" and PIPE_TO_SHELL.search(arguments):
            problems.append(f"RUN pipes a download into a shell: {arguments[:60]}")
        if keyword in {"ENV", "ARG"}:
            problems.extend(
                f"{keyword} {name} sets a secret-looking value in the image"
                for name, value in re.findall(r"(\w+)=(\S+)", arguments)
                if SECRET_NAME.search(name) and value not in {'""', "''"}
            )
    return problems


def pinned_image(reference: str) -> bool:
    """A tag other than latest, or a digest."""
    if DIGEST.search(reference):
        return True
    name = reference.rsplit("/", 1)[-1]
    return ":" in name and not name.endswith(":latest")


def audit_compose(data: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, service in (data.get("services") or {}).items():
        label = f"service {name}"
        if "build" in service:
            if service.get("read_only") is not True:
                problems.append(f"{label} is built here but its root filesystem is not read-only")
            if "ALL" not in (service.get("cap_drop") or []):
                problems.append(f"{label} does not drop all capabilities")
            if "no-new-privileges:true" not in (service.get("security_opt") or []):
                problems.append(f"{label} does not set no-new-privileges")
        if "image" in service and not pinned_image(str(service["image"])):
            problems.append(f"{label} uses an unpinned image {service['image']}")
        if service.get("privileged"):
            problems.append(f"{label} is privileged")
        if service.get("network_mode") == "host":
            problems.append(f"{label} uses the host network")
        problems.extend(
            f"{label} mounts the Docker socket"
            for volume in service.get("volumes") or []
            if "docker.sock" in str(volume)
        )
        problems.extend(
            f"{label} publishes {port} on every interface"
            for port in service.get("ports") or []
            if not str(port).startswith("127.0.0.1:")
        )
    return problems


def main() -> int:
    problems: list[str] = []
    for path in sorted(DEPLOYMENT.glob("Dockerfile.*")):
        if path.name.endswith(".dockerignore"):
            continue
        problems += [f"{path.relative_to(ROOT)}: {p}" for p in audit_dockerfile(path.read_text())]
    for path in sorted(DEPLOYMENT.glob("**/compose*.yaml")):
        problems += [
            f"{path.relative_to(ROOT)}: {p}"
            for p in audit_compose(yaml.safe_load(path.read_text()))
        ]
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print("Container definitions pass the audit.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
