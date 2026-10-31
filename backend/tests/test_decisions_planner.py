"""Planner selection, bounded failures and client ownership without paid calls."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from conftest import ASGIClientFactory
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from pydantic import SecretStr, ValidationError
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.decisions import Choice, Decision, FakeDecider, Question
from voice_delegate.delegation import planner as factory
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.scaling.worker_service import create_worker_app
from voice_delegate_agent.graph import DecisionsPlanner, LangGraphWorker, OfflinePlanner
from voice_delegate_agent.tools import TOOLS


def messages(goal: str = "calculate 2+2") -> list[AnyMessage]:
    return [
        SystemMessage(content="trusted"),
        HumanMessage(content=f"<goal>{goal}</goal>\n<context></context>"),
    ]


class ScriptedDecider(FakeDecider):
    def __init__(self, *values: str) -> None:
        super().__init__()
        self.values = iter(values)
        self.inputs: list[str] = []
        self.questions: list[Choice] = []

    async def decide(self, text: str, questions: tuple[Question, ...]) -> Decision:
        self.inputs.append(text)
        assert isinstance(questions[0], Choice)
        self.questions.append(questions[0])
        self.choice = next(self.values)
        result = await super().decide(text, questions)
        return Decision({}, 10, result.choices)


async def test_choice_runs_real_tool_then_only_final_prose() -> None:
    decider = ScriptedDecider("calculate", "direct")
    final = AsyncMock(return_value=AIMessage(content="Four"))
    fallback = AsyncMock()
    worker = LangGraphWorker(DecisionsPlanner(decider, final, fallback))
    result = await worker.delegate_task("calculate 2+2", "private fixture")
    assert result.text == "Four" and result.status == "completed"
    assert decider.calls == 2
    assert {o.value for o in decider.questions[0].choices} == {t.name for t in TOOLS} | {
        "direct",
        "refuse",
    }
    assert json.loads(decider.inputs[1])[-1]["content"] == "4"
    final.assert_awaited_once()
    fallback.respond.assert_not_awaited()


async def test_documentation_choice_preserves_cited_sources() -> None:
    decider = ScriptedDecider("search_documentation", "direct")
    offline = OfflinePlanner()
    result = await LangGraphWorker(
        DecisionsPlanner(decider, offline.respond, offline)
    ).delegate_task("docs fallback history", "")
    assert result.sources and "Documentation excerpt" in result.text
    assert result.status == "completed"


@pytest.mark.parametrize("choice", ["refuse", "api_refusal"])
async def test_refusal_does_not_invoke_text_or_fallback(choice: str) -> None:
    class Refusing(FakeDecider):
        async def decide(self, text: str, questions: tuple[Question, ...]) -> Decision:
            return Decision({}, refused=("next_action",))

    decider = Refusing() if choice == "api_refusal" else FakeDecider(choice="refuse")
    final, fallback = AsyncMock(), AsyncMock()
    answer = await DecisionsPlanner(decider, final, fallback).respond(messages())
    assert "no action taken" in answer.content
    assert not answer.tool_calls
    final.assert_not_awaited()
    fallback.respond.assert_not_awaited()


@pytest.mark.parametrize("mode", ["failure", "unknown", "missing", "timeout", "oversized"])
async def test_decision_failure_uses_existing_planner_once(mode: str) -> None:
    class Missing(FakeDecider):
        async def decide(self, text: str, questions: tuple[Question, ...]) -> Decision:
            return Decision({})

    class Slow(FakeDecider):
        async def decide(self, text: str, questions: tuple[Question, ...]) -> Decision:
            await asyncio.Event().wait()
            return Decision({})

    decider = (
        Missing()
        if mode == "missing"
        else Slow()
        if mode == "timeout"
        else FakeDecider(
            fail=mode == "failure", choice="unknown" if mode == "unknown" else "direct"
        )
    )
    final, fallback = AsyncMock(), AsyncMock()
    fallback.respond.return_value = AIMessage(content="Current behaviour")
    planner = DecisionsPlanner(decider, final, fallback, timeout=0.01)
    answer = await planner.respond(
        messages("x" * 32769 if mode == "oversized" else "calculate 2+2")
    )
    assert answer.content == "Current behaviour"
    assert answer.response_metadata["decision"]["fallback"] is True
    fallback.respond.assert_awaited_once()
    final.assert_not_awaited()


async def test_cancellation_propagates_without_paid_fallback() -> None:
    entered = asyncio.Event()

    class Slow(FakeDecider):
        async def decide(self, text: str, questions: tuple[Question, ...]) -> Decision:
            entered.set()
            await asyncio.Event().wait()
            return Decision({})

    fallback = AsyncMock()
    task = asyncio.create_task(DecisionsPlanner(Slow(), AsyncMock(), fallback).respond(messages()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    fallback.respond.assert_not_awaited()


@pytest.mark.parametrize("goal", ["two plus two", "calculate 1+__import__('os')", "1" * 161])
async def test_ambiguous_or_executable_arguments_require_clarification(goal: str) -> None:
    fallback, final = AsyncMock(), AsyncMock()
    result = await DecisionsPlanner(FakeDecider(choice="calculate"), final, fallback).respond(
        messages(goal)
    )
    assert not result.tool_calls and "clarify" in result.content
    final.assert_not_awaited()
    fallback.respond.assert_not_awaited()


async def test_final_model_cannot_introduce_tools_and_output_is_bounded() -> None:
    final = AsyncMock(
        return_value=AIMessage(
            content="",
            tool_calls=[{"name": "calculate", "args": {"expression": "2+2"}, "id": "unexpected"}],
        )
    )
    planner = DecisionsPlanner(FakeDecider(), final, OfflinePlanner())
    answer = await planner.respond(messages())
    assert not answer.tool_calls and "rejected" in answer.content
    final.return_value = AIMessage(content="é" * 10000)
    assert len(str((await planner.respond(messages())).content).encode()) <= 8192


@pytest.mark.parametrize("mode", ["openai", "decisions"])
def test_paid_worker_mode_requires_key(mode: str) -> None:
    with pytest.raises(ValidationError, match="require OPENAI_API_KEY"):
        Settings.model_validate({"worker_mode": mode, "OPENAI_API_KEY": ""})
    assert Settings().worker_mode == "offline"


@pytest.mark.parametrize("service", [False, True])
async def test_local_and_private_worker_factories_select_and_close_clients(
    service: bool, monkeypatch: pytest.MonkeyPatch, asgi_client: ASGIClientFactory, tmp_path: Path
) -> None:
    class TextModel:
        def __init__(self, api_key: str, model: str) -> None:
            self.respond = AsyncMock(return_value=AIMessage(content="fallback"))
            self.respond_final = AsyncMock(return_value=AIMessage(content="final"))
            self.aclose = AsyncMock()
            models.append(self)

    class Classifier(FakeDecider):
        def __init__(self, key: str, *, timeout: float) -> None:
            super().__init__()
            self.closed = 0
            classifiers.append(self)

        async def aclose(self) -> None:
            self.closed += 1

    models: list[TextModel] = []
    classifiers: list[Classifier] = []
    monkeypatch.setattr(factory, "OpenAIPlanner", TextModel)
    monkeypatch.setattr(factory, "OpenAIDecider", Classifier)
    settings = Settings(
        worker_mode="decisions",
        openai_api_key=SecretStr("offline-fixture"),
        worker_service_token=SecretStr("x" * 32),
        feedback_database=str(tmp_path / "feedback.sqlite3"),
    )
    app = create_worker_app(settings) if service else create_app(settings, FakeProvider())
    async with asgi_client(app):
        assert len(models) == len(classifiers) == 1
        models[0].respond.assert_not_awaited()
        assert classifiers[0].closed == 0
    models[0].aclose.assert_awaited_once()
    assert classifiers[0].closed == 1


async def test_tool_registry_is_dynamic_but_unknown_argument_builders_do_not_execute() -> None:
    from langchain_core.tools import tool

    @tool
    def read_example(topic: str) -> str:
        """Read a public example."""
        raise AssertionError("Unsupported tool arguments were executed")

    decider = ScriptedDecider("read_example")
    final = AsyncMock()
    planner = DecisionsPlanner(decider, final, OfflinePlanner(), tools=[read_example])
    result = await planner.respond(messages("Read an example"))
    assert [o.value for o in decider.questions[0].choices] == ["read_example", "direct", "refuse"]
    assert not result.tool_calls and "clarify" in result.content
    final.assert_not_awaited()


async def test_model_close_failure_still_closes_classifier() -> None:
    model, decider = AsyncMock(), AsyncMock()
    model.aclose.side_effect = RuntimeError("fixture close failure")
    runtime = factory.PlannerRuntime(OfflinePlanner(), model, decider)
    with pytest.raises(RuntimeError, match="fixture close failure"):
        await runtime.aclose()
    decider.aclose.assert_awaited_once()


async def test_remote_api_does_not_construct_paid_planner(
    monkeypatch: pytest.MonkeyPatch, asgi_client: ASGIClientFactory
) -> None:
    def forbidden(settings: Settings) -> None:
        raise AssertionError("Remote API constructed a local model")

    monkeypatch.setattr("voice_delegate.api.app.build_planner", forbidden)
    settings = Settings(worker_execution="remote", worker_service_token=SecretStr("x" * 32))
    async with asgi_client(create_app(settings, FakeProvider())) as client:
        assert (await client.get("/healthz")).status_code == 200


async def test_repeated_decisions_are_bounded_by_the_graph_step_limit() -> None:
    decider, final = FakeDecider(choice="calculate"), AsyncMock()
    answer = await LangGraphWorker(
        DecisionsPlanner(decider, final, OfflinePlanner()), 2
    ).delegate_task("calculate 2+2", "")
    assert answer.status == "failed" and "step limit" in answer.text
    assert decider.calls == 2
    final.assert_not_awaited()


async def test_rejected_final_tool_calls_are_reported_as_worker_failure() -> None:
    final = AsyncMock(
        return_value=AIMessage(
            content="",
            tool_calls=[{"name": "calculate", "args": {"expression": "2+2"}, "id": "unexpected"}],
        )
    )
    result = await LangGraphWorker(
        DecisionsPlanner(FakeDecider(), final, OfflinePlanner())
    ).delegate_task("calculate 2+2", "")
    assert result.status == "failed" and "rejected" in result.text


@pytest.mark.parametrize("valid", [False, True])
async def test_openai_final_path_uses_unbound_text_client(
    valid: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from voice_delegate_agent.graph import OpenAIPlanner

    response = AIMessage(content="Four") if valid else HumanMessage(content="not an assistant")
    invoke = AsyncMock(return_value=response)
    monkeypatch.setattr("langchain_openai.ChatOpenAI.ainvoke", invoke)
    model = OpenAIPlanner("offline-fixture", "offline")
    try:
        if valid:
            assert (await model.respond_final(messages())).content == "Four"
        else:
            with pytest.raises(ValueError, match="Unexpected worker response"):
                await model.respond_final(messages())
        invoke.assert_awaited_once_with(messages())
    finally:
        await model.aclose()
