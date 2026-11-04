"""Refuse files that must never be committed: environment files, keys and credentials.

AGENTS.md: never stage or commit `.env*` (except `.env.example`), `*.pem`, `*.key`, or files whose
names match `*secret*` or `*credential*`. Pass file names, or `--tracked` to check every tracked
file (CI) or `--staged` for the index (the pre-commit hook passes the names itself).
"""

import argparse
import fnmatch
import subprocess
import sys
from pathlib import PurePosixPath

ROOT_ALLOWED = {".env.example"}
BY_BASENAME = (".env*", "*.pem", "*.key", "*secret*", "*credential*")


def forbidden(path: str) -> str | None:
    """The rule a path breaks, or None. Matching is case-insensitive on the file name."""
    name = PurePosixPath(path).name.lower()
    if name in ROOT_ALLOWED:
        return None
    for pattern in BY_BASENAME:
        if fnmatch.fnmatchcase(name, pattern):
            return pattern
    return None


def git_files(*arguments: str) -> list[str]:
    """Paths from a git command, NUL-delimited so a quoted or non-ASCII name is read literally."""
    output = subprocess.run(
        ["git", *arguments, "-z"], capture_output=True, check=True
    ).stdout.decode()
    return [name for name in output.split("\0") if name]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--tracked", action="store_true", help="check every tracked file")
    parser.add_argument("--staged", action="store_true", help="check the files in the index")
    options = parser.parse_args(argv)
    paths = list(options.paths)
    if options.tracked:
        paths += git_files("ls-files")
    if options.staged:
        paths += git_files("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    failures = [(path, rule) for path in paths if (rule := forbidden(path))]
    for path, rule in failures:
        print(f"{path}: matches {rule}; this must never be committed", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
