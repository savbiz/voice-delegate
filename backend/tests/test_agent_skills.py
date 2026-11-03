"""Agent skills ship for Codex (.agents) and Claude Code (.claude) and must not drift."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / ".agents" / "skills"
MIRROR = ROOT / ".claude" / "skills"
FRONTMATTER = re.compile(r"\A---\nname: (?P<name>[a-z0-9-]+)\ndescription: (?P<desc>.+)\n---\n")


def files(base: Path) -> dict[str, str]:
    return {str(p.relative_to(base)): p.read_text() for p in sorted(base.rglob("*")) if p.is_file()}


def test_skill_directories_are_identical() -> None:
    assert files(CANONICAL), "no skills found"
    assert files(CANONICAL) == files(MIRROR)


def test_each_skill_has_matching_frontmatter() -> None:
    skills = [p for p in CANONICAL.iterdir() if p.is_dir()]
    assert skills
    for directory in skills:
        match = FRONTMATTER.match((directory / "SKILL.md").read_text())
        assert match, directory.name
        assert match["name"] == directory.name
        assert 20 <= len(match["desc"]) <= 400
