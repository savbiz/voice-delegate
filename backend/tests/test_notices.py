"""Attributions must cover direct dependencies and identify the bundled data."""

import hashlib
import json
import re
import tomllib
from pathlib import Path

import pytest

from scripts.build_notices import block, frontend_texts, section

ROOT = Path(__file__).resolve().parents[2]


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_every_declared_direct_dependency_has_an_attribution() -> None:
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    included = {normalize(name) for name in re.findall(r"^### `([^`]+)`", notices, re.M)}
    required = set()
    for path in [
        ROOT / "pyproject.toml",
        ROOT / "backend/pyproject.toml",
        ROOT / "agent/pyproject.toml",
    ]:
        config = tomllib.loads(path.read_text())
        dependencies = config["project"].get("dependencies", [])
        dependencies += config.get("build-system", {}).get("requires", [])
        for group in config.get("dependency-groups", {}).values():
            dependencies += [item for item in group if isinstance(item, str)]
        for group in config["project"].get("optional-dependencies", {}).values():
            dependencies += group
        for requirement in dependencies:
            match = re.match(r"[\w.-]+", requirement)
            assert match is not None
            required.add(normalize(match[0]))
    frontend = json.loads((ROOT / "frontend/package.json").read_text())
    for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        required.update(normalize(name) for name in frontend.get(key, {}))
    assert required <= included, f"Missing attributions: {sorted(required - included)}"


def test_bundled_tokenizer_attribution_matches_distributed_bytes() -> None:
    data = ROOT / "backend/src/voice_delegate/limits/data/o200k_base.tiktoken"
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    assert hashlib.sha256(data.read_bytes()).hexdigest() in notices
    assert data.with_name("LICENSE.tiktoken").read_text().strip() in notices
    assert "Redistributed unmodified under the terms of the tiktoken MIT licence." in notices


def test_all_licence_and_notice_files_are_reproduced(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("Primary licence text")
    nested = tmp_path / "vendor"
    nested.mkdir()
    (nested / "LICENSE").write_text("Vendored licence text")
    (nested / "NOTICE.txt").write_text("Upstream attribution")
    texts = frontend_texts(tmp_path)
    output = section("example", "1.0", "Apache-2.0", texts)
    assert len(texts) == 3
    for text in texts.values():
        assert text in output
    assert block("````embedded fence") == "`````text\n````embedded fence\n`````\n"


def test_missing_licence_text_stops_generation() -> None:
    with pytest.raises(ValueError, match="Missing licence text"):
        section("example", "1.0", "MIT", {})
