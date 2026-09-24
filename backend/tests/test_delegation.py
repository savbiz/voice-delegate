"""Exercise real LangGraph tools and cancellation races with all IP sockets disabled."""

import asyncio

import pytest
from conftest import BlockingWorker, eventually
from langchain_core.messages import AIMessage, AnyMessage
from voice_delegate.config import Settings
from voice_delegate.delegation.contracts import DELEGATE_TOOL, DelegationInput
from voice_delegate.delegation.history import History
from voice_delegate.delegation.runner import DelegationRunner, DelegationState
from voice_delegate.limits.tokens import count_tokens, truncate
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import (
    DelegationRequested,
    ProviderCapabilities,
    SpeechStarted,
    Transcript,
)
from voice_delegate.session.manager import SessionManager
from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner
from voice_delegate_agent.reference import WorkerResult
from voice_delegate_agent.tools import calculate


@pytest.mark.parametrize("text", ["ciao " * 200, "日本語🙂 " * 200, "<|endoftext|>" * 100])
@pytest.mark.parametrize("budget", [1, 8, 120])
def test_truncation_is_unicode_safe_and_bounded(text: str, budget: int) -> None:
    result = truncate(text, budget, max_bytes=500)
    assert count_tokens(result) <= budget
    assert len(result.encode()) <= 500
    assert "�" not in result
    assert result.endswith("…")


def test_short_result_and_single_tool_schema() -> None:
    assert truncate("42", 10) == "42"
    assert DELEGATE_TOOL["name"] == "delegate_task"
    with pytest.raises(ValueError):
        DelegationInput(goal="", context="")


@pytest.mark.parametrize("expression", ["__import__('os')", "9 ** 9999", "1 / 0", "1e20", "True"])
async def test_calculator_rejects_code_and_unbounded_operations(expression: str) -> None:
    assert "rejected" in await calculate.ainvoke({"expression": expression})


async def test_real_graph_uses_local_tool_without_network() -> None:
    worker = LangGraphWorker(OfflinePlanner())
    assert "244" in (await worker.delegate_task("calculate (120 + 80) * 1.22", "")).text
    assert "WebRTC" in (await worker.delegate_task("architecture", "")).text
    assert "No action" in (await worker.delegate_task("Book a flight", "")).text


async def test_graph_loop_is_finite() -> None:
    class LoopPlanner:
        async def respond(self, messages: list[AnyMessage]) -> AIMessage:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "calculate",
                        "args": {"expression": "1+1"},
                        "id": str(len(messages)),
                    }
                ],
            )

    worker = LangGraphWorker(LoopPlanner(), max_steps=2)
    assert "step limit" in (await worker.delegate_task("Keep going", "")).text


def test_history_merges_fragments_and_clamps_memory() -> None:
    history = History(budget=100)
    history.append(Transcript("user", "calculate ", 0, 100))
    history.append(Transcript("user", "2+2", 100, 200))
    assert history.goal() == "calculate 2+2"
    for i in range(40):
        history.append(
            Transcript("assistant" if i % 2 else "user", "🙂 " * 200, i * 1000, i * 1000 + 100)
        )
    assert len(history.entries) <= 12
    assert count_tokens(history.context()) <= 100


async def test_delegation_result_and_duplicate_are_delivered_once() -> None:
    provider = FakeProvider()
    manager = SessionManager(provider, Settings())
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    connection.queue.put_nowait(Transcript("user", "calculate 10 + 20", 0, 200))
    connection.queue.put_nowait(DelegationRequested("task", 300))
    connection.queue.put_nowait(DelegationRequested("task", 300))
    await eventually(lambda: bool(connection.commands))
    assert len(connection.commands) == 1
    assert "30" in connection.commands[0].content
    assert session.delegation.status == "completed"
    await manager.aclose()


async def test_timeout_cancels_worker_and_reports_failure(
    blocking_worker: BlockingWorker,
) -> None:
    provider = FakeProvider()
    worker = blocking_worker
    manager = SessionManager(provider, Settings(delegation_timeout_seconds=0.01), worker=worker)
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    connection.queue.put_nowait(Transcript("user", "calculate 1+1", 0, 100))
    connection.queue.put_nowait(DelegationRequested("task", 200))
    await eventually(lambda: bool(connection.commands))
    await worker.cancelled.wait()
    assert "timed out" in connection.commands[0].content
    assert session.delegation.status == "timeout"
    await manager.aclose()


@pytest.mark.parametrize("interrupt", ["transcript", "explicit", "close"])
async def test_interruption_and_close_never_narrate_late_result(
    blocking_worker: BlockingWorker, interrupt: str
) -> None:
    provider, worker = FakeProvider(), blocking_worker
    manager = SessionManager(provider, Settings(), worker=worker)
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    connection.queue.put_nowait(Transcript("user", "calculate 1+1", 0, 100))
    connection.queue.put_nowait(DelegationRequested("task", 200))
    await worker.started.wait()
    if interrupt == "transcript":
        connection.queue.put_nowait(Transcript("user", "Stop", 300, 400))
    elif interrupt == "explicit":
        manager.delegator.cancel(session.delegation)
    else:
        await manager.close(session)
    await worker.cancelled.wait()
    await eventually(lambda: not manager.delegator.work)
    assert connection.commands == []
    assert session.delegation.status == "cancelled"
    await manager.aclose()


async def test_failure_is_redacted_and_result_is_truncated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG", logger="voice_delegate.delegation.runner")

    class Worker:
        async def delegate_task(self, goal: str, context: str) -> WorkerResult:
            if goal == "fail":
                raise RuntimeError("PRIVATE ERROR DETAIL")
            return WorkerResult("日本語🙂 " * 1000)

    provider = FakeProvider()
    manager = SessionManager(provider, Settings(), worker=Worker())
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    runner = DelegationRunner(Worker(), budget=16)
    state = DelegationState()
    for goal in ["fail", "long"]:
        runner.start(state, goal, DelegationInput(goal=goal), connection, lambda: True)
        assert state.task is not None
        await state.task
    assert "Delegated worker failed" in caplog.text
    assert "PRIVATE ERROR DETAIL" in caplog.text
    assert "PRIVATE" not in connection.commands[0].content
    assert state.status == "completed"
    assert count_tokens(connection.commands[-1].content) <= 16
    await runner.aclose()
    await manager.aclose()


async def test_capacity_and_latest_task_supersedes_old_result(
    blocking_worker: BlockingWorker,
) -> None:
    worker, provider = blocking_worker, FakeProvider()
    manager = SessionManager(provider, Settings(), worker=worker)
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    runner = DelegationRunner(worker, capacity=1)
    first, second = DelegationState(), DelegationState()
    request = DelegationInput(goal="calculate 1+1")
    runner.start(first, "old", request, connection, lambda: True)
    await worker.started.wait()
    runner.start(second, "other-session", request, connection, lambda: True)
    assert second.task is not None
    await second.task
    assert second.status == "busy"
    assert "not started" in connection.commands[0].content
    runner.cancel(first)
    assert first.task is not None
    await asyncio.gather(first.task, return_exceptions=True)
    await runner.aclose()
    # A separate two-slot runner lets replacement execute during old-task cancellation.
    worker = BlockingWorker()
    runner = DelegationRunner(worker, capacity=2)
    first = DelegationState()
    runner.start(first, "old", request, connection, lambda: True)
    await worker.started.wait()
    worker.started.clear()
    runner.start(first, "replacement", request, connection, lambda: True)
    await worker.started.wait()
    worker.gate.set()
    assert first.task is not None
    await first.task
    assert first.status == "completed"
    assert connection.commands[-1].delegation_id == "replacement"
    assert connection.commands[-1].content == "done"
    assert worker.calls == 2
    assert all(command.delegation_id != "old" for command in connection.commands)
    await runner.aclose()
    await manager.aclose()


async def test_old_transcript_fragment_does_not_cancel_current_delegation(
    blocking_worker: BlockingWorker,
) -> None:
    worker, provider = blocking_worker, FakeProvider()
    manager = SessionManager(provider, Settings(), worker=worker)
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    connection.queue.put_nowait(Transcript("user", "calculate 1+1", 0, 100))
    connection.queue.put_nowait(DelegationRequested("task", 200))
    await worker.started.wait()
    connection.queue.put_nowait(Transcript("user", " please", 100, 150))
    await eventually(lambda: session.history.goal().endswith("please"))
    assert session.delegation.status == "running"
    await manager.aclose()


@pytest.mark.parametrize("fallback", [False, True])
async def test_realtime_interrupts_on_speech_not_delayed_transcript(
    blocking_worker: BlockingWorker, fallback: bool
) -> None:
    worker, realtime = blocking_worker, FakeProvider()
    realtime.capabilities = ProviderCapabilities(text_replay=True, transcript_timing=False)
    manager = SessionManager(
        FakeProvider() if fallback else realtime,
        Settings(),
        worker=worker,
        fallback=realtime if fallback else None,
    )
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    if fallback:
        await manager.reconnect(session, "v=0\r\n", 0)
    connection = realtime.connections[0]
    connection.queue.put_nowait(DelegationRequested("task", goal="calculate 1+1"))
    await worker.started.wait()
    connection.queue.put_nowait(Transcript("user", "calculate 1+1", 0, 0, committed=True))
    await eventually(lambda: bool(session.history.entries))
    assert session.delegation.status == "running"
    assert not worker.cancelled.is_set()
    connection.queue.put_nowait(SpeechStarted())
    await asyncio.wait_for(worker.cancelled.wait(), 1)
    assert session.delegation.status == "cancelled"
    assert not connection.commands
    await manager.aclose()


@pytest.mark.parametrize(("timing", "start_ms"), [(True, 0), (False, 1)])
async def test_real_transcript_timing_interrupts(
    blocking_worker: BlockingWorker, timing: bool, start_ms: int
) -> None:
    worker, provider = blocking_worker, FakeProvider()
    provider.capabilities = ProviderCapabilities(transcript_timing=timing)
    manager = SessionManager(provider, Settings(), worker=worker)
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    connection.queue.put_nowait(DelegationRequested("task", goal="calculate 1+1"))
    await worker.started.wait()
    connection.queue.put_nowait(Transcript("user", "stop", start_ms, start_ms))
    await asyncio.wait_for(worker.cancelled.wait(), 1)
    assert session.delegation.status == "cancelled"
    await manager.aclose()


@pytest.mark.parametrize("goal", ["calcola 2+2", "documentazione limiti"])
async def test_offline_planner_rejects_non_english_commands(goal: str) -> None:
    result = await LangGraphWorker(OfflinePlanner()).delegate_task(goal, "")
    assert "No action was taken" in result.text


@pytest.mark.parametrize("goal", ["calculate 2+2", "docs limits"])
async def test_offline_planner_keeps_english_commands(goal: str) -> None:
    result = await LangGraphWorker(OfflinePlanner()).delegate_task(goal, "")
    assert ("4" if goal.startswith("calculate") else "Documentation excerpt") in result.text


@pytest.mark.parametrize("failure", ["validation", "runtime", "value"])
async def test_graph_distinguishes_invalid_input_from_tool_failure(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from langchain_core.messages import ToolMessage
    from langchain_core.tools import tool
    from voice_delegate_agent import graph

    @tool
    async def broken(value: int) -> str:
        """A tool whose execution always fails."""
        if failure == "value":
            raise ValueError("private execution detail")
        raise RuntimeError("private execution detail")

    monkeypatch.setattr(graph, "TOOLS", [broken])

    class Planner:
        async def respond(self, messages: list[AnyMessage]) -> AIMessage:
            if isinstance(messages[-1], ToolMessage):
                return AIMessage(content=str(messages[-1].content))
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "broken",
                        "args": {} if failure == "validation" else {"value": 1},
                        "id": "failure",
                    }
                ],
            )

    result = await LangGraphWorker(Planner()).delegate_task("test", "")
    assert result.text == (
        "Tool input invalid; no action taken."
        if failure == "validation"
        else "Tool failed; no action taken."
    )


async def test_graph_rejects_non_ai_message_at_tool_execution() -> None:
    from langchain_core.messages import HumanMessage

    worker = LangGraphWorker(OfflinePlanner())
    with pytest.raises(ValueError, match="Tool execution requires an AIMessage"):
        await worker.graph.nodes["tools"].ainvoke(
            {"messages": [HumanMessage(content="invalid")], "steps": 0, "source_ids": []}
        )
