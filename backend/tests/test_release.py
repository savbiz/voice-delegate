"""Release metadata and tag validation agree across all packages."""

import json
import runpy
import tomllib
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
release = SimpleNamespace(**runpy.run_path(str(ROOT / "scripts/check_release.py")))


def test_all_package_versions_match_installed_backend() -> None:
    expected = version("voice-delegate")
    for name in ("pyproject.toml", "backend/pyproject.toml", "agent/pyproject.toml"):
        assert tomllib.loads((ROOT / name).read_text())["project"]["version"] == expected
    assert json.loads((ROOT / "frontend/package.json").read_text())["version"] == expected


@pytest.mark.parametrize("tag", ["v0.1.1", "0.1.0", "v0.1.0-rc.1", ""])
def test_wrong_release_tag_fails(tag: str) -> None:
    with pytest.raises(ValueError, match="must equal"):
        release.check_tag(tag, "0.1.0")


def test_matching_release_tag_passes() -> None:
    release.check_tag("v0.1.0", "0.1.0")
