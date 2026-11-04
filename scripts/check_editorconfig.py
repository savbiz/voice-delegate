"""Check the whitespace rules in .editorconfig: LF line endings, a final newline, no trailing
whitespace, and no tab indentation (except in a Makefile).

Generated and vendored files are exempt (see EXEMPT). Pass file names, or `--tracked` to check
every tracked text file (CI).
"""

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
# Mirrors the sections of .editorconfig that set these rules to `unset`.
EXEMPT = (
    "frontend/android/*",
    "frontend/ios/*",
    "uv.lock",
    "frontend/pnpm-lock.yaml",
    "THIRD_PARTY_NOTICES.md",
    "LICENSE*",
    "*/LICENSE*",
    "*.tiktoken",
    "backend/src/voice_delegate/limits/data/*",  # vendored tokenizer data
)


def exempt(path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in EXEMPT)


def check_text(path: str, data: bytes) -> list[str]:
    """Problems in one file's bytes; binary and non-UTF-8 content is skipped."""
    if b"\0" in data:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    problems = []
    if b"\r" in data:
        problems.append("contains CR line endings; use LF")
    if text and not text.endswith("\n"):
        problems.append("has no final newline")
    tabs_allowed = PurePosixPath(path).name == "Makefile"
    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.rstrip("\r")
        if stripped != stripped.rstrip():
            problems.append(f"line {number} has trailing whitespace")
        leading = stripped[: len(stripped) - len(stripped.lstrip(" \t"))]
        if not tabs_allowed and "\t" in leading:
            problems.append(f"line {number} is indented with a tab")
    return problems


def tracked() -> list[str]:
    """Tracked paths, NUL-delimited so git never quotes or escapes an unusual name."""
    output = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True, cwd=ROOT
    ).stdout.decode()
    return [name for name in output.split("\0") if name]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--tracked", action="store_true", help="check every tracked file")
    options = parser.parse_args(argv)
    paths = list(options.paths) + (tracked() if options.tracked else [])
    failed = False
    for path in paths:
        file = Path(path)
        if exempt(file.as_posix()) or not file.is_file():
            continue
        for problem in check_text(file.as_posix(), file.read_bytes()):
            failed = True
            print(f"{path}: {problem}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
