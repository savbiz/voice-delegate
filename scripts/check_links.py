"""Check relative Markdown link destinations in non-ignored repository files.

Run from any directory with Python 3.12+. Includes images and reference definitions;
ignores external URLs, code, and comments. URL fragments/queries do not affect the
filesystem destination check. Git excludes dependencies and generated artifacts.
"""

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def prose(text: str) -> str:
    """Mask non-prose while preserving line numbers for diagnostics."""
    pattern = r"(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1[^\n]*(?:\n|$)"
    for expression in (pattern, r"(?s)<!--.*?-->", r"(`+)[^`]*?\1"):
        text = re.sub(expression, lambda m: re.sub(r"[^\n]", " ", m[0]), text)
    return text


def destinations(text: str) -> list[tuple[int, str]]:
    """Read inline destinations (including balanced parentheses) and definitions."""
    found: list[tuple[int, str]] = []
    starts = [m.end() for m in re.finditer(r"\]\(\s*", text)]
    starts += [m.end() for m in re.finditer(r"(?m)^ {0,3}\[(?!\^)[^]\n]+\]:\s*", text)]
    for start in starts:
        pos = start
        depth = 0
        angled = text[start : start + 1] == "<"
        if angled:
            pos += 1
            start = pos
        while pos < len(text):
            char = text[pos]
            if char == "\\" and pos + 1 < len(text):
                pos += 2
                continue
            if angled:
                if char == ">":
                    break
            elif char == "(":
                depth += 1
            elif char == ")":
                if not depth:
                    break
                depth -= 1
            elif char.isspace():
                break
            pos += 1
        found.append((text.count("\n", 0, start) + 1, text[start:pos]))
    return found


def main() -> int:
    names = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )
    failures = []
    count = 0
    for name in sorted(set(names)):
        source = ROOT / name
        if source.suffix.lower() != ".md" or not source.is_file():
            continue
        count += 1
        for line, destination in destinations(prose(source.read_text())):
            destination = re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]^_`{|}~])", r"\1", destination)
            url = urlsplit(destination)
            if url.scheme or url.netloc:
                continue
            path = unquote(url.path)
            target = ROOT / path.lstrip("/") if path.startswith("/") else source.parent / path
            if path and not target.exists():
                failures.append(f"{name}:{line}: missing destination: {destination}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Relative Markdown links resolve in {count} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
