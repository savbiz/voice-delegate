"""Decide whether a pull request changes only documentation.

The ci workflow uses this to skip the frontend job, the container build and the Python 3.13
run for changes they cannot affect. Backend lint, types, tests and the documentation checks
still run. Reads changed paths from standard input, one per line (a rename lists both its old
and new path), and prints `true` or `false`. Anything unexpected prints `false`: a wrong
`false` only costs minutes, a wrong `true` would skip a check.

Markdown under src/ directories is deliberately not documentation: the prompt blocks are
runtime inputs that ship in the container.
"""

import sys
from fnmatch import fnmatchcase

DOCUMENTATION = (
    "docs/*",
    ".github/ISSUE_TEMPLATE/*",
    ".github/pull_request_template.md",
    ".agents/*.md",
    ".claude/*.md",
    "README.md",
    "*/README.md",
    "AGENTS.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
)
# GitHub stops listing a pull request's files at this count, so a longer list may be partial.
MAX_PATHS = 3000


def is_documentation(path: str) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in DOCUMENTATION)


def docs_only(paths: list[str]) -> bool:
    return 0 < len(paths) < MAX_PATHS and all(is_documentation(path) for path in paths)


def main() -> int:
    paths = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
    print("true" if docs_only(paths) else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
