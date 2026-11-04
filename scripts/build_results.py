"""Build the nightly results page from the numbers a CI run measured.

Inputs are the files the nightly workflow produces: a JUnit report and a coverage report from the
test suite, the Locust statistics from scripts/loadtest.py, and the offline worker-eval report.
The output is `results.json` (this run plus a bounded history) and a self-contained `index.html`
with no script and no external resource.

    uv run python -m scripts.build_results --junit junit.xml --coverage coverage.json \
        --loadtest-csv run_stats.csv --eval-report offline.json --output-dir site

Nothing here is a provider measurement: the load test and the evals use the offline stack.
"""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from scripts.loadtest import AGGREGATED, Row, parse_stats

SCHEMA = 1
HISTORY_LIMIT = 90
LOAD_ENDPOINTS = ("create session", "connect offer", "heartbeat", "close session")
RESULT_ROW = "delegation result"
SHED_ROW = "shed at capacity"


def parse_junit(text: str) -> dict[str, float]:
    """Totals from a pytest JUnit report."""
    root = ET.fromstring(text)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    failed = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    return {
        "passed": total - failed - skipped,
        "failed": failed,
        "skipped": skipped,
        "seconds": round(sum(float(s.get("time", 0)) for s in suites), 1),
    }


def parse_coverage(text: str) -> float:
    return round(float(json.loads(text)["totals"]["percent_covered"]), 2)


def summarize_load(rows: list[Row], users: int, duration: str, outcome: str) -> dict[str, Any]:
    by_name = {row.name: row for row in rows}
    total = by_name.get(AGGREGATED)
    shed = by_name.get(SHED_ROW)
    return {
        "users": users,
        "duration": duration,
        "outcome": outcome,
        "requests": total.requests if total else 0,
        "failures": total.failures if total else 0,
        "shed": shed.requests if shed else 0,
        "endpoints": [
            {
                "name": name,
                "requests": by_name[name].requests,
                "failures": by_name[name].failures,
                "p50_ms": by_name[name].p50_ms,
                "p95_ms": by_name[name].p95_ms,
                "p99_ms": by_name[name].p99_ms,
            }
            for name in (*LOAD_ENDPOINTS, RESULT_ROW)
            if name in by_name
        ],
    }


def summarize_evals(report: dict[str, Any]) -> dict[str, Any]:
    summary, metadata = report["summary"], report["metadata"]
    return {
        "dataset": metadata["dataset"],
        "mode": metadata["mode"],
        "total": summary["total"],
        "executed": summary["executed"],
        "skipped": summary["skipped"],
        "failed": summary["failed"],
        "scores": summary["scores"],
        "plumbing": summary["plumbing"],
        "p50_worker_ms": round(summary["p50_worker_seconds"] * 1000, 2),
        "p95_worker_ms": round(summary["p95_worker_seconds"] * 1000, 2),
    }


def build_entry(
    *,
    commit: str,
    when: datetime,
    tests: dict[str, float] | None,
    coverage: float | None,
    load: dict[str, Any] | None,
    evals: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "date": when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "tests": tests,
        "coverage_percent": coverage,
        "loadtest": load,
        "evals": evals,
    }


def merge_history(previous: dict[str, Any] | None, entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Append this run to the earlier history, keeping the newest HISTORY_LIMIT runs."""
    history = list(previous.get("history", [])) if previous else []
    history = [item for item in history if item.get("date") != entry["date"]]
    history.append(entry)
    return history[-HISTORY_LIMIT:]


def result_p95(entry: dict[str, Any]) -> float | None:
    for endpoint in (entry.get("loadtest") or {}).get("endpoints", []):
        if endpoint["name"] == RESULT_ROW:
            return float(endpoint["p95_ms"])
    return None


def sparkline(values: list[float | None], width: int = 160, height: int = 32) -> str:
    """An inline SVG polyline of the values, skipping gaps; empty when fewer than two points."""
    points = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(points) < 2:
        return ""
    low, high = min(v for _, v in points), max(v for _, v in points)
    span = (high - low) or 1.0
    last = max(len(values) - 1, 1)
    coordinates = " ".join(
        f"{i / last * (width - 4) + 2:.1f},{height - 3 - (v - low) / span * (height - 6):.1f}"
        for i, v in points
    )
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="trend, {len(points)} runs"><polyline points="{coordinates}" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>'
    )


def newest(values: list[float | None]) -> float | None:
    return next((value for value in reversed(values) if value is not None), None)


def cell(value: object, unit: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value}{unit}"


STYLE = """
:root { color-scheme: light dark; --bg:#fbfbfa; --fg:#1c1b19; --muted:#6a675f; --line:#dedbd2;
  --card:#ffffff; --good:#1a7f4b; --bad:#b3261e; --accent:#2a5bd7; }
@media (prefers-color-scheme: dark) { :root { --bg:#161614; --fg:#ecebe6; --muted:#a09d94;
  --line:#34322d; --card:#1e1d1a; --good:#5fcf94; --bad:#ff8a80; --accent:#8ab0ff; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:56rem; margin:0 auto; padding:2rem 1rem 4rem; }
h1 { font-size:1.6rem; margin:0 0 .25rem; } h2 { font-size:1.15rem; margin:2.2rem 0 .6rem; }
p, li { max-width:46rem; } .muted { color:var(--muted); font-size:.9rem; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(10rem,1fr)); gap:.75rem;
  margin:1.25rem 0; }
.card { background:var(--card); border:1px solid var(--line); border-radius:.6rem;
  padding:.8rem 1rem; }
.card b { display:block; font-size:1.55rem; line-height:1.2; font-variant-numeric:tabular-nums; }
.card span { color:var(--muted); font-size:.85rem; }
.table { overflow-x:auto; } table { border-collapse:collapse; width:100%; font-size:.92rem; }
th, td { text-align:right; padding:.4rem .6rem; border-bottom:1px solid var(--line);
  font-variant-numeric:tabular-nums; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; } th { color:var(--muted); font-weight:600; }
.good { color:var(--good); } .bad { color:var(--bad); } .spark { width:10rem; height:2rem;
  color:var(--accent); vertical-align:middle; }
code { font-size:.9em; } a { color:var(--accent); }
"""


def render_html(page: dict[str, Any]) -> str:
    latest = page["latest"]
    history = page["history"]
    tests, load, evals = latest["tests"], latest["loadtest"], latest["evals"]
    e = escape
    cards = []
    if tests:
        bad = " bad" if tests["failed"] else " good"
        cards.append(
            f'<div class="card"><b class="{bad.strip()}">{tests["passed"]:.0f} passed</b>'
            f"<span>{tests['failed']:.0f} failed, {tests['skipped']:.0f} skipped</span></div>"
        )
    if latest["coverage_percent"] is not None:
        cards.append(
            f'<div class="card"><b>{latest["coverage_percent"]}%</b>'
            "<span>line coverage</span></div>"
        )
    result = result_p95(latest)
    if result is not None:
        cards.append(
            f'<div class="card"><b>{result:.0f} ms</b><span>delegated result, p95, '
            f"{load['users']} users</span></div>"
        )
    if load:
        verdict = "good" if load["failures"] == 0 else "bad"
        cards.append(
            f'<div class="card"><b class="{verdict}">{load["failures"]} failures</b>'
            f"<span>of {load['requests']} requests, {load['shed']} shed</span></div>"
        )
    if evals:
        cards.append(
            f'<div class="card"><b>{evals["executed"] - evals["failed"]}/{evals["executed"]}</b>'
            f"<span>offline worker cases ({evals['skipped']} skipped)</span></div>"
        )
    sections = [f'<div class="cards">{"".join(cards)}</div>']
    if load and load["endpoints"]:
        rows = "".join(
            f"<tr><td>{e(item['name'])}</td><td>{item['requests']}</td><td>{item['failures']}</td>"
            f"<td>{item['p50_ms']:.0f}</td><td>{item['p95_ms']:.0f}</td><td>{item['p99_ms']:.0f}</td></tr>"
            for item in load["endpoints"]
        )
        sections.append(
            f'<h2>Load test</h2><p class="muted">{load["users"]} concurrent virtual users for '
            f"{e(load['duration'])} against an isolated offline backend (scripted voice provider, "
            "offline worker, loopback). Latencies are in milliseconds; "
            f"outcome of the budget check: <b>{e(str(load['outcome']))}</b>.</p>"
            '<div class="table"><table><thead><tr><th>Endpoint</th><th>Requests</th>'
            "<th>Failures</th><th>p50</th><th>p95</th><th>p99</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )
    if evals:
        scores = "".join(
            f"<tr><td>{e(name)}</td><td>{value:.2f}</td></tr>"
            for name, value in {**evals["scores"], **evals["plumbing"]}.items()
        )
        sections.append(
            f'<h2>Offline worker evaluation</h2><p class="muted">Dataset {e(evals["dataset"])}, '
            f"{evals['total']} cases ({evals['executed']} executed, {evals['skipped']} need a live "
            "model). The scripted offline planner answers, so a perfect score is a <b>control "
            "check of the retrieval, tool and citation plumbing</b>, not a measure of model "
            f"quality. Worker time p50 {evals['p50_worker_ms']} ms, "
            f"p95 {evals['p95_worker_ms']} ms.</p>"
            '<div class="table"><table><thead><tr><th>Check</th><th>Score</th></tr></thead>'
            f"<tbody>{scores}</tbody></table></div>"
        )
    trend = [
        ("Delegated result p95 (ms)", [result_p95(item) for item in history]),
        ("Line coverage (%)", [item.get("coverage_percent") for item in history]),
        (
            "Tests passed",
            [(item.get("tests") or {}).get("passed") for item in history],
        ),
    ]
    trend_rows = "".join(
        f"<tr><td>{e(name)}</td><td>{cell(newest(values))}</td>"
        f"<td>{sparkline(values) or 'not enough runs yet'}</td></tr>"
        for name, values in trend
    )
    sections.append(
        f'<h2>Trend</h2><p class="muted">The last {len(history)} nightly '
        f"{'run' if len(history) == 1 else 'runs'}.</p>"
        '<div class="table"><table><thead><tr><th>Measure</th><th>Latest</th><th>History</th></tr>'
        f"</thead><tbody>{trend_rows}</tbody></table></div>"
    )
    limits = (
        "<h2>What this does not show</h2><ul>"
        "<li>No voice-provider measurement: audio never flows, and no model is called.</li>"
        "<li>The runner is a shared GitHub-hosted machine, so absolute latencies vary from night "
        "to night; compare trends, not single values.</li>"
        "<li>Live voice quality and latency are recorded separately, with real providers, in the "
        'repository\'s <a href="https://github.com/savbiz/voice-delegate/blob/main/docs/benchmarks.md">'
        "benchmark notes</a>.</li></ul>"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>voice-delegate nightly results</title>"
        f"<style>{STYLE}</style></head><body><main>"
        "<h1>voice-delegate: nightly results</h1>"
        f'<p class="muted">Measured by CI on {e(latest["date"])} for commit '
        f'<code><a href="https://github.com/savbiz/voice-delegate/commit/{e(latest["commit"])}">'
        f"{e(latest['commit'][:9])}</a></code>. Numbers come from the offline stack: nothing "
        "here calls a provider or costs money.</p>"
        f"{''.join(sections)}{limits}</main></body></html>\n"
    )


def read(path: str | None) -> str | None:
    return Path(path).read_text() if path and Path(path).is_file() else None


def render_markdown(page: dict[str, Any]) -> str:
    """The same headline numbers as a GitHub job summary."""
    latest = page["latest"]
    lines = [f"### Nightly results for `{latest['commit'][:9]}` ({latest['date']})", ""]
    if latest["tests"]:
        t = latest["tests"]
        lines.append(
            f"- Tests: {t['passed']:.0f} passed, {t['failed']:.0f} failed, "
            f"{t['skipped']:.0f} skipped"
        )
    if latest["coverage_percent"] is not None:
        lines.append(f"- Coverage: {latest['coverage_percent']}%")
    if (p95 := result_p95(latest)) is not None:
        lines.append(f"- Delegated result p95: {p95:.0f} ms")
    if latest["loadtest"]:
        lo = latest["loadtest"]
        lines.append(
            f"- Load test: {lo['requests']} requests, {lo['failures']} failures, "
            f"{lo['shed']} shed ({lo['outcome']})"
        )
    if latest["evals"]:
        ev = latest["evals"]
        passed = ev["executed"] - ev["failed"]
        lines.append(f"- Offline worker evals: {passed}/{ev['executed']} executed cases pass")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--junit")
    parser.add_argument("--coverage")
    parser.add_argument("--loadtest-csv")
    parser.add_argument("--loadtest-users", type=int, default=0)
    parser.add_argument("--loadtest-duration", default="")
    parser.add_argument("--loadtest-outcome", default="unknown")
    parser.add_argument("--eval-report")
    parser.add_argument("--previous", help="earlier results.json, to extend the history")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    options = parser.parse_args(argv)

    junit, coverage = read(options.junit), read(options.coverage)
    csv_text, eval_text = read(options.loadtest_csv), read(options.eval_report)
    previous_text = read(options.previous)
    try:
        previous = json.loads(previous_text) if previous_text else None
    except json.JSONDecodeError:
        previous = None  # a damaged earlier file must not stop tonight's page
    entry = build_entry(
        commit=options.commit,
        when=datetime.now(UTC),
        tests=parse_junit(junit) if junit else None,
        coverage=parse_coverage(coverage) if coverage else None,
        load=(
            summarize_load(
                parse_stats(csv_text),
                options.loadtest_users,
                options.loadtest_duration,
                options.loadtest_outcome,
            )
            if csv_text
            else None
        ),
        evals=summarize_evals(json.loads(eval_text)) if eval_text else None,
    )
    if not any([entry["tests"], entry["loadtest"], entry["evals"]]):
        print(
            "No measurement files were found; refusing to publish an empty page.", file=sys.stderr
        )
        return 1
    page = {"schema": SCHEMA, "latest": entry, "history": merge_history(previous, entry)}
    options.output_dir.mkdir(parents=True, exist_ok=True)
    (options.output_dir / "results.json").write_text(json.dumps(page, indent=2) + "\n")
    (options.output_dir / "index.html").write_text(render_html(page))
    (options.output_dir / "summary.md").write_text(render_markdown(page))
    print(render_markdown(page))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
