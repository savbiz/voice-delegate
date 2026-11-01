"""Citations survive every narration boundary or the task fails within its budgets."""

import time
from uuid import uuid4

import pytest
from voice_delegate.config import Settings
from voice_delegate.delegation.contracts import DelegationInput
from voice_delegate.delegation.intent import IntentRunner, Portfolio
from voice_delegate.delegation.intent import Job as IntentJob
from voice_delegate.delegation.runner import DelegationRunner, DelegationState
from voice_delegate.limits.results import clip_worker_result
from voice_delegate.limits.tokens import count_tokens
from voice_delegate.providers.fake import FakeConnection
from voice_delegate.scaling.worker_service import Job, JobInput, Jobs
from voice_delegate_agent.reference import WorkerResult
from voice_delegate_agent.web_search import web_source


class CitedWorker:
    async def delegate_task(self, goal: str, context: str) -> WorkerResult:
        source = web_source("https://example.org/notice", "Public notice", "A public update.")
        assert source is not None
        return WorkerResult("Public details " * 200 + " [1]", (source,))


@pytest.mark.parametrize(("budget", "max_bytes"), [(16, 500), (10000, 80), (8, 40)])
async def test_clipping_never_completes_an_uncited_web_answer(budget: int, max_bytes: int) -> None:
    result = await CitedWorker().delegate_task("", "")
    clipped = clip_worker_result(result, budget, max_bytes=max_bytes)
    assert clipped.status == "failed"
    assert clipped.sources == ()
    assert "Public details" not in clipped.text
    assert count_tokens(clipped.text) <= budget
    assert len(clipped.text.encode()) <= max_bytes


async def test_retained_citation_keeps_evidence_and_original_status() -> None:
    result = await CitedWorker().delegate_task("", "")
    result = WorkerResult("Update [1]. " + result.text, result.sources)
    clipped = clip_worker_result(result, 16)
    assert clipped.status == "completed"
    assert clipped.sources == result.sources
    assert "[1]" in clipped.text
    assert count_tokens(clipped.text) <= 16


async def test_direct_delegation_marks_citation_loss_failed() -> None:
    runner = DelegationRunner(CitedWorker(), budget=16)
    connection = FakeConnection()
    state = DelegationState()
    try:
        runner.start(
            state,
            "request",
            DelegationInput(goal="public update", context=""),
            connection,
            lambda: True,
        )
        assert state.task is not None
        await state.task
        assert state.status == "failed"
        assert state.sources == ()
        assert "lost its citations" in connection.commands[-1].content
    finally:
        await runner.aclose()


async def test_private_worker_marks_citation_loss_failed() -> None:
    jobs = Jobs(CitedWorker(), Settings(delegation_result_tokens=16))
    job = Job("test", time.time() + 30)
    await jobs.run(
        job, JobInput(request_id=uuid4(), goal="public update", deadline=time.time() + 30)
    )
    assert job.status == "failed"
    assert job.source_ids == ()
    assert job.web_sources == ()
    assert "lost its citations" in job.text


@pytest.mark.parametrize("goal", ["Original request " * 20, "Original request [1] " * 20])
async def test_delayed_delivery_rechecks_after_adding_preamble(goal: str) -> None:
    runner = DelegationRunner(CitedWorker(), budget=32)
    intent = IntentRunner(runner, Settings(), time.monotonic, None)
    source = web_source("https://example.org/notice", "Public notice", "Update.")
    assert source is not None
    # The original fits; only adding the request reminder removes the final citation.
    result = WorkerResult("Public update " * 12 + "[1]", (source,))
    assert count_tokens(result.text) <= runner.budget
    job = IntentJob("request", goal, time.monotonic(), 0)
    intent._pending(job, result)
    assert job.result is not None
    assert job.result.status == "failed"
    assert job.result.sources == ()
    assert "lost its citations" in job.result.text

    portfolio = Portfolio(
        jobs={job.id: job}, activity_at=time.monotonic(), quiet_since=time.monotonic() - 1
    )
    connection = FakeConnection()
    await intent.deliver(portfolio, connection, 0)
    assert job.status == "failed"
    assert portfolio.sources == ()
    assert "lost its citations" in connection.commands[-1].content
