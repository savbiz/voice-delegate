"""Prevent reintroducing the dependency versions covered by the two security alerts."""

import re
import tomllib
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]


def test_locked_sdk_has_the_auth_actions_fix_and_current_attribution() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    versions = [p["version"] for p in lock["package"] if p["name"] == "langgraph-sdk"]
    assert versions
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    for version in versions:
        assert Version(version) >= Version("0.4.4")
        assert f"### `langgraph-sdk` {version}\n" in notices


def test_all_locked_source_map_copies_have_the_offset_fix_and_current_attribution() -> None:
    lock = (ROOT / "frontend/pnpm-lock.yaml").read_text()
    versions = set(re.findall(r"^  source-map-js@([^:]+):", lock, re.MULTILINE))
    assert versions
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    for version in versions:
        assert Version(version) >= Version("1.2.2")
        assert f"### `source-map-js` {version}\n" in notices


def test_frontend_lockfile_has_no_duplicate_package_or_snapshot_keys() -> None:
    lock = (ROOT / "frontend/pnpm-lock.yaml").read_text()
    packages, snapshots = lock.split("\npackages:\n", 1)[1].split("\nsnapshots:\n", 1)
    for section in (packages, snapshots):
        keys = re.findall(r"^  (\S.*?):(?: .*)?$", section, re.MULTILINE)
        assert keys
        assert len(keys) == len(set(keys)), "Duplicate package keys break frozen installs"


def test_runtime_locks_exclude_compromised_roots_and_unbounded_trace_parsing() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    versions = {
        package["name"]: package["version"] for package in lock["package"] if "version" in package
    }
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    for package, minimum in {"certifi": "2026.10.19", "opentelemetry-api": "1.45.1"}.items():
        assert Version(versions[package]) >= Version(minimum)
        assert f"### `{package}` {versions[package]}\n" in notices


def test_vite_copies_include_development_server_security_fixes() -> None:
    lock = (ROOT / "frontend/pnpm-lock.yaml").read_text()
    versions = set(re.findall(r"^  vite@([^:(]+)", lock, re.MULTILINE))
    assert versions
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    for version in versions:
        assert Version(version) >= Version("8.3.3")
        assert f"### `vite` {version}\n" in notices
