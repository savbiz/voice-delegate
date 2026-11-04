"""The nightly results page is built from measured files; no measurement means no page."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scripts import build_results as results

JUNIT = """<?xml version="1.0"?>
<testsuites>
  <testsuite name="pytest" tests="10" failures="1" errors="1" skipped="2" time="12.34"/>
</testsuites>"""
COVERAGE = json.dumps({"totals": {"percent_covered": 93.8123}})
HEADER = "Type,Name,Request Count,Failure Count,50%,95%,99%\n"
CSV = HEADER + "".join(
    f"POST,{name},{n},{f},{p50},{p95},{p99}\n"
    for name, n, f, p50, p95, p99 in [
        ("create session", 100, 0, 3, 40, 40),
        ("connect offer", 90, 0, 3, 20, 20),
        ("heartbeat", 400, 0, 4, 12, 12),
        ("close session", 80, 0, 3, 8, 8),
        ("delegation result", 90, 0, 210, 230, 230),
        ("shed at capacity", 10, 0, 2, 5, 5),
        ("Aggregated", 770, 0, 4, 210, 230),
    ]
)
EVALS: dict[str, Any] = {
    "metadata": {"dataset": "worker-v4", "mode": "offline"},
    "summary": {
        "total": 40,
        "executed": 36,
        "skipped": 4,
        "failed": 0,
        "scores": {"numeric_result": 1.0},
        "plumbing": {"tool_selection": 1.0},
        "p50_worker_seconds": 0.0051,
        "p95_worker_seconds": 0.0067,
    },
}
WHEN = datetime(2026, 11, 5, 3, 11, tzinfo=UTC)


def entry(**overrides: Any) -> dict[str, Any]:
    from scripts.loadtest import parse_stats

    values: dict[str, Any] = {
        "commit": "a" * 40,
        "when": WHEN,
        "tests": results.parse_junit(JUNIT),
        "coverage": results.parse_coverage(COVERAGE),
        "load": results.summarize_load(parse_stats(CSV), 40, "30s", "success"),
        "evals": results.summarize_evals(EVALS),
    }
    values.update(overrides)
    return results.build_entry(**values)


def test_junit_totals_count_errors_as_failures_and_skips_separately() -> None:
    assert results.parse_junit(JUNIT) == {"passed": 6, "failed": 2, "skipped": 2, "seconds": 12.3}


def test_a_single_testsuite_root_is_read_too() -> None:
    assert (
        results.parse_junit('<testsuite tests="3" failures="0" skipped="0" time="1"/>')["passed"]
        == 3
    )


def test_coverage_is_rounded_to_two_places() -> None:
    assert results.parse_coverage(COVERAGE) == 93.81


def test_load_summary_keeps_the_named_endpoints_and_counts_shedding() -> None:
    from scripts.loadtest import parse_stats

    load = results.summarize_load(parse_stats(CSV), 40, "30s", "success")
    assert [item["name"] for item in load["endpoints"]] == [
        "create session",
        "connect offer",
        "heartbeat",
        "close session",
        "delegation result",
    ]
    assert (load["requests"], load["failures"], load["shed"], load["users"]) == (770, 0, 10, 40)
    assert results.result_p95({"loadtest": load}) == 230


def test_eval_summary_reports_worker_time_in_milliseconds() -> None:
    summary = results.summarize_evals(EVALS)
    assert (summary["executed"], summary["skipped"], summary["failed"]) == (36, 4, 0)
    assert (summary["p50_worker_ms"], summary["p95_worker_ms"]) == (5.1, 6.7)


def test_history_appends_replaces_a_repeat_and_keeps_the_newest_ninety() -> None:
    first = entry()
    assert results.merge_history(None, first) == [first]
    assert results.merge_history({"history": [first]}, first) == [first]
    old = [{"date": f"2026-01-{i:02d}T00:00:00Z"} for i in range(1, 29)] * 4
    merged = results.merge_history({"history": old}, first)
    assert len(merged) == results.HISTORY_LIMIT and merged[-1] == first


def test_a_sparkline_needs_two_points_and_survives_flat_or_gappy_data() -> None:
    assert results.sparkline([]) == "" and results.sparkline([None, 5.0, None]) == ""
    flat = results.sparkline([3.0, 3.0, 3.0])
    assert "<polyline" in flat
    gappy = results.sparkline([1.0, None, 3.0, 2.0])
    coordinates = re.findall(r"([\d.]+),([\d.]+)", gappy.split('points="')[1].split('"')[0])
    assert len(coordinates) == 3
    assert all(0 <= float(x) <= 160 and 0 <= float(y) <= 32 for x, y in coordinates)


def page(**overrides: Any) -> dict[str, Any]:
    latest = entry(**overrides)
    return {"schema": 1, "latest": latest, "history": [latest]}


def test_the_page_shows_the_measured_numbers_and_what_they_are_not() -> None:
    html = results.render_html(page())
    for expected in ("6 passed", "93.81%", "230 ms", "0 failures", "36/36", "delegation result"):
        assert expected in html, expected
    assert "control check" in html and "does not show" in html
    assert "aaaaaaaaa" in html  # the short commit


def test_the_page_is_self_contained_and_scriptless() -> None:
    html = results.render_html(page())
    assert "<script" not in html and "<link" not in html and "<img" not in html
    urls = set(re.findall(r"https?://[^\"' <)]+", html))
    assert all(url.startswith("https://github.com/savbiz/voice-delegate") for url in urls), urls
    assert "prefers-color-scheme: dark" in html and 'name="viewport"' in html


def test_a_hostile_commit_string_cannot_inject_markup() -> None:
    html = results.render_html(page(commit='"><script>alert(1)</script>' + "b" * 20))
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_failures_are_flagged_and_missing_sections_are_left_out() -> None:
    failing = results.render_html(
        page(tests={"passed": 5, "failed": 3, "skipped": 0, "seconds": 1.0}, load=None, evals=None)
    )
    assert 'class="bad"' in failing
    assert "Load test" not in failing and "Offline worker evaluation" not in failing


def write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def arguments(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--junit", write(tmp_path, "junit.xml", JUNIT),
        "--coverage", write(tmp_path, "coverage.json", COVERAGE),
        "--loadtest-csv", write(tmp_path, "stats.csv", CSV),
        "--loadtest-users", "40", "--loadtest-duration", "30s", "--loadtest-outcome", "success",
        "--eval-report", write(tmp_path, "evals.json", json.dumps(EVALS)),
        "--commit", "c" * 40, "--output-dir", str(tmp_path / "site"),
        *extra,
    ]  # fmt: skip


def test_main_writes_the_page_the_data_and_a_summary(tmp_path: Path) -> None:
    assert results.main(arguments(tmp_path)) == 0
    site = tmp_path / "site"
    data = json.loads((site / "results.json").read_text())
    assert data["schema"] == 1 and len(data["history"]) == 1
    assert data["latest"]["commit"] == "c" * 40
    assert "6 passed" in (site / "index.html").read_text()
    assert "Delegated result p95: 230 ms" in (site / "summary.md").read_text()


def test_main_extends_an_earlier_history_and_survives_a_damaged_one(tmp_path: Path) -> None:
    earlier = {"history": [{"date": "2026-11-04T03:00:00Z", "commit": "d" * 40}]}
    previous = write(tmp_path, "previous.json", json.dumps(earlier))
    assert results.main(arguments(tmp_path, "--previous", previous)) == 0
    history = json.loads((tmp_path / "site" / "results.json").read_text())["history"]
    assert [item["commit"] for item in history] == ["d" * 40, "c" * 40]
    damaged = write(tmp_path, "damaged.json", "{not json")
    assert results.main(arguments(tmp_path, "--previous", damaged)) == 0


def test_main_refuses_to_publish_without_any_measurement(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = results.main(["--commit", "e" * 40, "--output-dir", str(tmp_path / "site")])
    assert code == 1
    assert "refusing to publish an empty page" in capsys.readouterr().err
    assert not (tmp_path / "site").exists()


def test_a_whole_number_is_shown_without_a_decimal_and_one_run_is_singular() -> None:
    assert results.cell(220.0) == "220" and results.cell(94.12) == "94.12"
    assert results.cell(None) == "n/a" and results.cell(1080) == "1080"
    html = results.render_html(page())
    assert "last 1 nightly run." in html and "220.0" not in html


def test_the_nightly_workflow_measures_everything_and_publishes_only_when_enabled() -> None:
    import yaml  # type: ignore[import-untyped]

    root = Path(__file__).resolve().parents[2]
    text = (root / ".github/workflows/results.yml").read_text()
    workflow = yaml.safe_load(text)
    assert "schedule" in (workflow.get("on") or workflow[True])
    commands = " ".join(str(s.get("run", "")) for s in workflow["jobs"]["measure"]["steps"])
    for part in ("pytest", "loadtest.py", "worker_eval", "scripts.build_results"):
        assert part in commands, part
    # Nothing is exposed until the owner opts in, and only the publish job may write Pages.
    assert "vars.PUBLISH_RESULTS == 'true'" in workflow["jobs"]["publish"]["if"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["publish"]["permissions"] == {"pages": "write", "id-token": "write"}
    assert "permissions" not in workflow["jobs"]["measure"]
    # A broken check must still surface: the measurements continue on error, then the run fails.
    steps = {s.get("id"): s for s in workflow["jobs"]["measure"]["steps"]}
    assert all(steps[name]["continue-on-error"] is True for name in ("tests", "load", "evals"))
    assert "exit 1" in text
