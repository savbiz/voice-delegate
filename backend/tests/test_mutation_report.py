"""The mutation-testing wrapper's parsing and verdict logic, without running any mutant."""

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
mutation = SimpleNamespace(**runpy.run_path(str(ROOT / "scripts/mutation.py")))

RESULTS = """\
    voice_delegate.admission.policy.xǁAdmissionǁ_reserve__mutmut_3: survived
    voice_delegate.admission.policy.xǁAdmissionǁ_reserve__mutmut_9: survived
    voice_delegate.limits.http.xǁBodyLimitMiddlewareǁ__call____mutmut_31: survived
    voice_delegate.limits.http.xǁBodyLimitMiddlewareǁ__call____mutmut_32: killed
    voice_delegate.limits.tokens.x_truncate__mutmut_34: not checked
"""


def test_stats_are_read_and_scored_with_timeouts_counted_as_detected() -> None:
    text = json.dumps({"killed": 80, "survived": 10, "timeout": 10, "total": 100})
    stats = mutation.parse_stats(text)
    assert (stats.detected, stats.survived, stats.total) == (90, 10, 100)
    assert stats.score == pytest.approx(90.0)


def test_crashed_test_processes_are_reported_and_never_counted_as_detected() -> None:
    stats = mutation.parse_stats(
        json.dumps({"killed": 90, "survived": 5, "timeout": 0, "segfault": 5, "total": 100})
    )
    assert stats.crashed == 5
    assert stats.score == pytest.approx(90.0)
    assert "crashed: 5" in mutation.report(stats, mutation.Counter())


def test_an_incomplete_run_is_detected_from_unjudged_mutants() -> None:
    complete = mutation.parse_stats(
        json.dumps({"killed": 90, "survived": 5, "timeout": 1, "segfault": 2, "skipped": 1,
                    "suspicious": 0, "no_tests": 1, "total": 100})
    )  # fmt: skip
    assert complete.unchecked == 0
    partial = mutation.parse_stats(json.dumps({"killed": 60, "survived": 5, "total": 100}))
    assert partial.unchecked == 35
    interrupted = mutation.parse_stats(
        json.dumps({"killed": 100, "survived": 0, "total": 100, "check_was_interrupted_by_user": 1})
    )
    assert interrupted.interrupted == 1 and interrupted.unchecked == 0


def test_a_run_without_mutants_scores_zero_instead_of_dividing_by_zero() -> None:
    stats = mutation.parse_stats(json.dumps({"killed": 0, "survived": 0, "total": 0}))
    assert stats.score == 0.0


def test_only_survivors_are_counted_and_grouped_by_function() -> None:
    counts = mutation.survivors_by_function(RESULTS)
    assert counts == {
        "admission.policy.xǁAdmissionǁ_reserve": 2,
        "limits.http.xǁBodyLimitMiddlewareǁ__call__": 1,
    }


def test_the_report_names_the_score_and_the_worst_functions() -> None:
    stats = mutation.Stats(killed=630, survived=77, timeout=0, total=707)
    text = mutation.report(stats, mutation.survivors_by_function(RESULTS))
    assert "score: 89.1%" in text
    assert text.index("_reserve") < text.index("BodyLimitMiddleware")


def test_the_workflow_and_the_configuration_target_the_same_code() -> None:
    import tomllib

    config = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())["tool"]["mutmut"]
    assert config["only_mutate"] == [
        "src/voice_delegate/limits/*.py",
        "src/voice_delegate/admission/*.py",
    ]
    # Every test file the mutants are checked against must exist, or mutmut finds no tests.
    for selected in config["pytest_add_cli_args_test_selection"]:
        assert (ROOT / "backend" / selected).is_file(), selected
    workflow = (ROOT / ".github/workflows/mutation.yml").read_text()
    assert "scripts/mutation.py --min-score" in workflow
    assert "--group mutation" in workflow
