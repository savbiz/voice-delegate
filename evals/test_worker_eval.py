"""Verify scoring detects regressions without paid models or cloud access."""

import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from voice_delegate_agent.reference import source_by_id

from evals.worker_eval import DATASET, Budget, ObservedPlanner, run_cases, score

CASES = json.loads(DATASET.read_text())["cases"]


def test_dataset_is_versioned_unique_and_grounded() -> None:
    assert len(CASES) == 32
    assert len({c["id"] for c in CASES}) == 32
    assert all(c["goal"] and c["expected"]["rubric"] for c in CASES)
    for case in CASES:
        for source in case["expected"].get("source_ids", []):
            assert source_by_id(source) is not None


def test_scorers_detect_wrong_number_evidence_and_citation() -> None:
    out = {"text": "5", "source_ids": [], "tools": ["calculate"], "status": "completed"}
    assert score(CASES[0], out)["numeric_result"] == 0
    out["text"] = "4"
    assert score(CASES[0], out)["numeric_result"] == 1
    out["text"] = "The result of 2+2 is 4."
    assert score(CASES[0], out)["numeric_result"] == 1
    out = {
        "text": "Invented answer [99]",
        "source_ids": [str(uuid4())],
        "tools": [],
        "status": "completed",
    }
    result = score(CASES[12], out)
    assert result["valid_source_ids"] == 0
    assert result["citation_indices_valid"] == 0
    assert result["expected_evidence_retrieved"] == 0
    assert result["tool_selection"] == 0
    out["text"] = "long " * 500
    assert score(CASES[12], out)["bounded_output"] == 0


async def test_offline_run_has_no_paid_calls_and_skips_language_quality() -> None:
    report = await run_cases(CASES, "offline", "unused", 0)
    summary = report["summary"]
    assert summary["executed"] == 28 and summary["skipped"] == 4
    assert summary["model_calls"] == 0
    assert summary["scores"]["numeric_result"] == 1
    assert summary["plumbing"]["valid_source_ids"] == 1
    assert summary["plumbing"]["no_sources"] == 1
    assert summary["scores"]["expected_evidence_retrieved"] >= 11 / 12
    assert set(summary["scores"]) == {"numeric_result", "expected_evidence_retrieved"}
    assert report["metadata"]["n_trials"] == 1
    assert summary["score_counts"]["expected_evidence_retrieved"] == 12
    assert "judge_correctness" not in summary["scores"]


async def test_budget_blocks_before_extra_model_call() -> None:
    class Model:
        calls = 0

        async def respond(self, messages: object) -> AIMessage:
            self.calls += 1
            return AIMessage(
                content="4",
                usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            )

    model = Model()
    budget = Budget(1)
    planner = ObservedPlanner(model, budget, True)
    await planner.respond([])
    with pytest.raises(RuntimeError, match="budget exhausted"):
        await planner.respond([])
    assert model.calls == 1
    assert budget.input_tokens == 10 and budget.output_tokens == 2


def test_cli_requires_explicit_paid_budget_and_upload_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from evals import worker_eval

    monkeypatch.setattr(worker_eval, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    for argv in [
        ["eval", "--mode", "openai"],
        ["eval", "--mode", "openai", "--allow-paid", "--max-model-calls", "1"],
        ["eval", "--judge-model", "gpt-4.1-mini"],
        ["eval", "--upload"],
    ]:
        monkeypatch.setattr("sys.argv", argv)
        with pytest.raises(SystemExit) as exc:
            worker_eval.main()
        assert exc.value.code == 2


async def test_cloud_upload_is_explicit_and_uses_only_curated_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from types import SimpleNamespace

    from evals.worker_eval import upload

    logged = []
    initialized = {}

    def init(**kwargs):
        initialized.update(kwargs)
        return SimpleNamespace(
            log=lambda **row: logged.append(row),
            flush=lambda: None,
            summarize=lambda: "experiment-summary",
        )

    monkeypatch.setitem(sys.modules, "braintrust", SimpleNamespace(init=init))
    monkeypatch.setitem(
        sys.modules,
        "braintrust.git_fields",
        SimpleNamespace(GitMetadataSettings=lambda **kwargs: kwargs),
    )
    monkeypatch.setenv("BRAINTRUST_API_KEY", "test-private-key")
    report = await run_cases(CASES[:1], "offline", "unused", 0)
    assert upload(report, CASES[:1], "test-project") == "experiment-summary"
    assert initialized["set_current"] is False
    assert initialized["git_metadata_settings"] == {"collect": "none"}
    assert len(logged) == 1
    assert logged[0]["input"] == {"goal": CASES[0]["goal"], "context": ""}
    assert "test-private-key" not in json.dumps(logged)
