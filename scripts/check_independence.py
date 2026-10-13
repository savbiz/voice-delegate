"""Check tracked content without printing prohibited terms or matching source lines."""

import argparse
import ast
import re
import subprocess
from datetime import datetime
from pathlib import Path

FORBIDDEN_TERMS = (
    "miro",
    "sidekick",
    "canvas",
    "rishat",
    "henrik",
    "core-ai",
    "ai-realtime",
    "ai-proxy",
)

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = "scripts/check_independence.py"
LOCK_FILES = {"uv.lock", "frontend/pnpm-lock.yaml"}


def mask_declaration(text: str) -> str:
    """Exempt only string literals in the one top-level policy declaration."""
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != "FORBIDDEN_TERMS":
            continue
        if not isinstance(node.value, ast.Tuple):
            continue
        for value in node.value.elts:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            assert value.end_lineno is not None
            assert value.end_col_offset is not None
            for number in range(value.lineno, value.end_lineno + 1):
                # AST column offsets count UTF-8 bytes, not Unicode characters.
                line = lines[number - 1].encode()
                start = value.col_offset if number == value.lineno else 0
                end = (
                    value.end_col_offset
                    if number == value.end_lineno
                    else len(line.rstrip(b"\r\n"))
                )
                lines[number - 1] = (line[:start] + b" " * (end - start) + line[end:]).decode()
    return "".join(lines)


def check(
    root: Path, terms: tuple[str, ...] = FORBIDDEN_TERMS, *, staged: bool = False
) -> list[str]:
    """Inspect tracked working files, or the exact index snapshot used by a commit."""
    if not terms or any(not term for term in terms):
        message = "The independence policy must contain non-empty terms."
        raise ValueError(message)
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, terms)) + r")(?!\w)", re.I)
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    failures = []
    for name in sorted(set(names) - LOCK_FILES - {""}):
        if pattern.search(name):
            failures.append("A tracked filename contains a prohibited term (path withheld).")
            continue
        path = root / name
        if staged:
            content = subprocess.check_output(["git", "show", ":" + name], cwd=root)
        elif path.is_symlink():
            content = str(path.readlink()).encode()
        elif path.is_file():
            content = path.read_bytes()
        else:
            continue
        text = content.decode("utf-8", errors="replace")
        if name == GUARD_PATH:
            text = mask_declaration(text)
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                failures.append(f"{name}:{number}: prohibited term (content withheld)")
    return failures


def work_hours(now: datetime) -> bool:
    """Use the caller's local wall clock; warnings never change the exit code."""
    return now.weekday() < 5 and 9 <= now.hour < 18


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staged", action="store_true", help="Scan the Git index, not working files"
    )
    parser.add_argument("--warn-work-hours", action="store_true")
    args = parser.parse_args()
    if args.warn_work_hours and work_hours(datetime.now().astimezone()):
        print("Warning: local weekday working hours (09:00-18:00); review personal-work timing.")
    failures = check(ROOT, staged=args.staged)
    if failures:
        print("\n".join(failures))
        return 1
    print("Independence check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
