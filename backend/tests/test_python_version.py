"""The project supports exactly one Python version; every place that names it must agree."""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSION = "3.14"
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))


def toml(path: str) -> dict[str, object]:
    return tomllib.loads((ROOT / path).read_text())


@pytest.mark.parametrize(
    "path", ["pyproject.toml", "backend/pyproject.toml", "agent/pyproject.toml"]
)
def test_packages_require_the_supported_python(path: str) -> None:
    project = toml(path)["project"]
    assert isinstance(project, dict)
    assert project["requires-python"] == f">={VERSION}"


def test_tools_target_the_supported_python() -> None:
    tool = toml("pyproject.toml")["tool"]
    assert isinstance(tool, dict)
    assert tool["ruff"]["target-version"] == "py" + VERSION.replace(".", "")
    assert tool["mypy"]["python_version"] == VERSION
    assert (ROOT / ".python-version").read_text().strip() == VERSION


def test_container_image_uses_the_supported_python() -> None:
    images = re.findall(
        r"^FROM (python:[^@\s]+)", (ROOT / "deployment/Dockerfile.backend").read_text(), re.M
    )
    assert images
    assert set(images) == {f"python:{VERSION}-slim"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflows_use_the_supported_python(path: Path) -> None:
    versions = re.findall(r"python(?:-version)?: ?\"?(3\.\d+)", path.read_text())
    assert set(versions) <= {VERSION}
