"""Snapshot generation excludes scaffolding and detects documentation drift."""

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

build_reference = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/build_reference.py"))
)


def test_builder_excludes_code_links_and_single_lines(tmp_path: Path) -> None:
    (tmp_path / "docs/decisions").mkdir(parents=True)
    for path in build_reference.documents(tmp_path):
        path.write_text("# Title\n")
    prose = "Evidence stays intact across\nwrapped source lines."
    long_word = "x" * 1700
    (tmp_path / "README.md").write_text(
        "# Title\n\nSingle line ignored.\n\n"
        "```python\nnot evidence\nnot evidence either\n```\n\n"
        "~~~\nalso excluded\nsecond code line\n~~~\n\n"
        "[one](one.md)\n[two](two.md)\n\n"
        "[![badge](image.svg)](target)\n[link](elsewhere)\n\n"
        f"## Evidence\n\n{prose}\n\n{long_word}\nlast word\n"
    )
    entries = json.loads(build_reference.build(tmp_path))
    assert [entry["text"] for entry in entries] == [prose, long_word, "last word"]
    assert {entry["section"] for entry in entries} == {"Evidence"}


def test_snapshot_check_detects_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "snapshot.json"
    monkeypatch.setattr("sys.argv", ["build_reference", "--output", str(output)])
    build_reference.main()
    monkeypatch.setattr("sys.argv", ["build_reference", "--output", str(output), "--check"])
    build_reference.main()
    output.write_text("[]\n")
    with pytest.raises(SystemExit, match="drifted"):
        build_reference.main()
