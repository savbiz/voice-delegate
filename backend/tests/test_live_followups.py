"""Offline regressions for overlapping transcripts and opted-in task diagnostics."""

import json
from pathlib import Path

from conftest import ASGIClientFactory, FakeClock
from fastapi import FastAPI
from voice_delegate.api.routes import build_router
from voice_delegate.config import Settings
from voice_delegate.debug import DebugRecording
from voice_delegate.delegation.contracts import DelegationInput
from voice_delegate.delegation.history import History
from voice_delegate.delegation.intent import IntentRunner, Portfolio
from voice_delegate.delegation.runner import DelegationRunner
from voice_delegate.providers.fake import FakeConnection, FakeProvider
from voice_delegate.providers.models import DelegationRequested, Transcript
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.preferences import VoicePreferences
from voice_delegate_agent.reference import WorkerResult

from test_support import eventually


class ContextWorker:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    async def delegate_task(self, goal: str, context: str) -> WorkerResult:
        self.requests.append((goal, context))
        return WorkerResult("Eight")


async def test_overlap_preserves_goal_recap_and_context_for_a_correction() -> None:
    provider, worker = FakeProvider(), ContextWorker()
    manager = SessionManager(provider, Settings(intent_cancellation=True), worker=worker)
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    try:
        for event in (
            Transcript("user", "Calculate four plus", 100, 200),
            Transcript("assistant", "Checking", 200, 300),
            Transcript("user", " four", 400, 500),
            Transcript("assistant", " now.", 500, 600),
            DelegationRequested("one"),
        ):
            provider.connections[0].queue.put_nowait(event)
        await eventually(lambda: len(worker.requests) == 1)
        assert worker.requests[0][0] == "Calculate four plus four"
        assert session.recap.latest_request == "Calculate four plus four"
        assert session.recap.latest_reply == "Checking now."
        provider.connections[0].queue.put_nowait(
            Transcript("user", "Use the calculator for that", 2000, 2200)
        )
        provider.connections[0].queue.put_nowait(DelegationRequested("two"))
        await eventually(lambda: len(worker.requests) == 2)
        assert worker.requests[1][0] == "Use the calculator for that"
        assert "user: Calculate four plus four" in worker.requests[1][1]
        assert "user: Use the calculator for that" in worker.requests[1][1]
    finally:
        await manager.aclose()


def test_turn_context_is_bounded_and_committed_utterances_stay_separate() -> None:
    history = History(budget=64)
    history.append(Transcript("user", "First", 0, 0, True))
    history.append(Transcript("user", "Second", 0, 0, True))
    assert history.goal() == "Second"
    assert history.context() == "user: First\nuser: Second"
    for index in range(40):
        history.append(Transcript("assistant", "word " * 4000, index, index + 1, True))
    from voice_delegate.limits.tokens import count_tokens

    assert len(history.turns) <= 12
    assert count_tokens(history.context()) <= history.budget


async def test_debug_separates_execution_from_delivery_wait_without_recording_task_text(
    tmp_path: Path, fake_clock: FakeClock
) -> None:
    debug = DebugRecording(tmp_path / "debug", "fixture")
    worker = ContextWorker()
    base = DelegationRunner(worker)
    runner = IntentRunner(base, Settings(intent_cancellation=True), fake_clock, None)
    state = Portfolio(debug=debug)
    try:
        runner.start(
            state, "task", DelegationInput(goal="private goal", context="private context"), 0
        )
        await eventually(lambda: state.jobs["task"].status == "pending")
        fake_clock.advance(4)
        runner.activity(state, 0, speaking=False)
        fake_clock.advance(0.7)
        await runner.deliver(state, FakeConnection(), 0)
        job = state.jobs["task"]
        work, wait = job.durations(fake_clock())
        assert work == 0
        assert 4.6 < wait < 4.8
        fake_clock.advance(10)
        assert job.durations(fake_clock()) == (work, wait)
        rows = [json.loads(line) for line in debug.path.read_text().splitlines()]
        assert [row["event"] for row in rows] == ["task_started", "task_ready", "task_sent"]
        assert rows[-1]["delivery_wait_seconds"] == wait
        assert "private" not in debug.path.read_text()
        assert "Eight" not in debug.path.read_text()
    finally:
        await runner.close(state)
        await base.aclose()


async def test_browser_debug_reports_portfolio_state_only_with_consent(
    asgi_client: ASGIClientFactory, tmp_path: Path
) -> None:
    manager = SessionManager(
        FakeProvider(),
        Settings(
            intent_cancellation=True, debug_recording=True, debug_directory=str(tmp_path / "debug")
        ),
    )
    session = manager.create(preferences=VoicePreferences(debug_recording=True))
    app = FastAPI()
    app.include_router(build_router(manager))
    try:
        manager.intent.start(session.portfolio, "task", DelegationInput(goal="calculate 4+4"), 0)
        async with asgi_client(app) as client:
            client.headers.update({"Origin": "http://localhost:5173", "X-Session-Key": session.key})
            response = await client.post(
                f"/api/sessions/{session.id}/debug", json={"event": "stats"}
            )
            assert response.status_code == 200
        assert session.debug is not None
        rows = [json.loads(line) for line in session.debug.path.read_text().splitlines()]
        assert (
            next(row for row in rows if row["event"] == "browser_stats")["worker_state"]
            == "running"
        )
        other = manager.create()
        assert other.debug is None and other.portfolio.debug is None
        instructions = manager.config(session).instructions
        assert "omit that topic" in instructions
        assert "operands that are already present" in instructions
    finally:
        await manager.aclose()


def test_quick_new_turn_after_reply_is_not_joined_to_previous_request() -> None:
    history = History()
    history.append(Transcript("user", "First request", 100, 200))
    history.append(Transcript("assistant", "Answer", 300, 400))
    history.append(Transcript("user", "New request", 500, 600))
    assert history.goal() == "New request"
    assert history.context() == "user: First request\nassistant: Answer\nuser: New request"
