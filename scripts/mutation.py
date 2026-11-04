"""Run mutation testing on the limits and admission code and enforce a minimum score.

Mutation testing changes the code in small ways (flip a comparison, drop a check, edit a
message) and runs the tests against each change. A change the tests do not notice is a surviving
mutant: a behaviour no test pins down. Line coverage cannot see that, because the line ran.

    uv sync --locked --group mutation
    uv run --group mutation python scripts/mutation.py --min-score 85

The configuration is in backend/pyproject.toml ([tool.mutmut]). mutmut runs from backend/ so it
sees the standard src/ layout, with the repository root on PYTHONPATH for the shared test helper.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SURVIVOR = re.compile(r"^\s*(?P<name>\S+?)__mutmut_\d+: survived\s*$")


@dataclass(frozen=True)
class Stats:
    killed: int
    survived: int
    timeout: int
    total: int
    crashed: int = 0

    @property
    def detected(self) -> int:
        """A mutant is detected when a test failed or hung on it."""
        return self.killed + self.timeout

    @property
    def score(self) -> float:
        return 100 * self.detected / self.total if self.total else 0.0


def parse_stats(text: str) -> Stats:
    """Read the file written by ``mutmut export-cicd-stats``."""
    data = json.loads(text)
    return Stats(
        killed=int(data["killed"]),
        survived=int(data["survived"]),
        timeout=int(data.get("timeout", 0)),
        total=int(data["total"]),
        crashed=int(data.get("segfault", 0)),
    )


def survivors_by_function(results: str) -> Counter[str]:
    """Count surviving mutants per function from ``mutmut results`` output."""
    counts: Counter[str] = Counter()
    for line in results.splitlines():
        match = SURVIVOR.match(line)
        if match:
            counts[match["name"].removeprefix("voice_delegate.")] += 1
    return counts


def report(stats: Stats, survivors: Counter[str], top: int = 12) -> str:
    lines = [
        f"mutants: {stats.total}  detected: {stats.detected}  survived: {stats.survived}  "
        f"crashed: {stats.crashed}  score: {stats.score:.1f}%",
        "most survivors by function:",
    ]
    lines += [f"  {count:>3}  {name}" for name, count in survivors.most_common(top)]
    return "\n".join(lines)


# The console script, not `python -m mutmut`: run as a module, mutmut forks its test processes in a
# way that reports surviving mutants as segfaults.
MUTMUT = str(Path(sys.executable).with_name("mutmut"))


def run(arguments: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [MUTMUT, *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--min-score", type=float, default=85.0, help="fail below this percentage")
    parser.add_argument(
        "--keep", action="store_true", help="reuse backend/mutants from a prior run"
    )
    options = parser.parse_args(argv)
    environment = dict(os.environ, PYTHONPATH=str(ROOT))
    if not options.keep:
        shutil.rmtree(BACKEND / "mutants", ignore_errors=True)
    result = subprocess.run([MUTMUT, "run"], cwd=BACKEND, env=environment, check=False)
    if result.returncode not in (0, 1):  # mutmut exits 1 when mutants survive
        print(f"mutmut failed with exit code {result.returncode}", file=sys.stderr)
        return 2
    run(["export-cicd-stats"], environment)
    stats_file = BACKEND / "mutants" / "mutmut-cicd-stats.json"
    if not stats_file.exists():
        print("mutmut wrote no statistics", file=sys.stderr)
        return 2
    stats = parse_stats(stats_file.read_text())
    print(report(stats, survivors_by_function(run(["results"], environment).stdout)))
    if stats.score < options.min_score:
        print(f"FAIL: score {stats.score:.1f}% is below {options.min_score:.1f}%", file=sys.stderr)
        return 1
    print(f"Mutation score {stats.score:.1f}% meets the {options.min_score:.1f}% minimum.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
