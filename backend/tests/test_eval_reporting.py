"""Evaluation failures remain visible in denominators without paid requests."""

import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage
from voice_delegate_agent.reference import WorkerResult

EVAL = runpy.run_path(str(Path(__file__).resolve().parents[2] / "evals/worker_eval.py"))


def test_eval_metadata_without_git(monkeypatch: pytest.MonkeyPatch) -> None:
    metadata = EVAL["metadata"]
    monkeypatch.setattr("subprocess.run", Mock(side_effect=FileNotFoundError))
    result = metadata("offline", "scripted", None)
    assert result["commit"] is None
    assert result["tracked_changes"] is None
    assert result["n_trials"] == 1


async def test_judge_average_counts_worker_failure_as_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    run_cases = EVAL["run_cases"]
    worker = SimpleNamespace(
        delegate_task=AsyncMock(side_effect=[WorkerResult("4"), RuntimeError("worker failed")])
    )
    judged = {
        "raw": AIMessage(content=""),
        "parsed": EVAL["JudgeScore"](correctness=1, usefulness=1, groundedness=1),
    }
    judge = SimpleNamespace(
        with_structured_output=Mock(
            return_value=SimpleNamespace(ainvoke=AsyncMock(return_value=judged))
        ),
        root_async_client=SimpleNamespace(close=AsyncMock()),
        root_client=SimpleNamespace(close=Mock()),
    )
    factory = Mock(return_value=judge)
    monkeypatch.setitem(run_cases.__globals__, "LangGraphWorker", Mock(return_value=worker))
    monkeypatch.setitem(run_cases.__globals__, "ChatOpenAI", factory)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    cases = [
        {
            "id": str(i),
            "kind": "arithmetic",
            "goal": "calculate 2+2",
            "context": "",
            "offline": True,
            "expected": {"number": 4, "rubric": "4"},
        }
        for i in range(2)
    ]
    report = await run_cases(cases, "offline", "unused", 1, "fake-judge")
    assert factory.call_args.kwargs["temperature"] == 0
    assert report["summary"]["scores"]["judge_correctness"] == 0.5
    assert report["summary"]["score_counts"]["judge_correctness"] == 2
    assert report["rows"][1]["judge_status"] == "skipped_worker_failure"
    assert report["summary"]["plumbing"]["completed"] == 0.5
    assert "completed" not in report["summary"]["scores"]
    judge.root_async_client.close.assert_awaited_once()
