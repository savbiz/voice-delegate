"""Compare worker planners with scripted controls or explicitly authorized paid models."""

import asyncio
import hashlib
import json
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from voice_delegate.decisions.openai import OpenAIDecider
from voice_delegate.limits.tokens import truncate
from voice_delegate_agent.decisions import (
    Choice,
    Decider,
    Decision,
    FakeDecider,
    Question,
    Selection,
)
from voice_delegate_agent.graph import (
    DecisionsPlanner,
    LangGraphWorker,
    OfflinePlanner,
    OpenAIPlanner,
    Planner,
)


class ScriptedChoiceDecider(FakeDecider):
    """Exercise the choice interface using the existing English-command script, not labels."""

    async def decide(self, text: str, questions: tuple[Question, ...]) -> Decision:
        self.calls += 1
        messages: list[AnyMessage] = []
        for row in json.loads(text):
            if row["role"] == "system":
                messages.append(SystemMessage(content=row["content"]))
            elif row["role"] == "human":
                messages.append(HumanMessage(content=row["content"]))
            elif row["role"] == "tool":
                messages.append(ToolMessage(content=row["content"], tool_call_id="scripted"))
            elif row["role"] == "ai":
                messages.append(
                    AIMessage(content=row["content"], tool_calls=row.get("tool_calls", []))
                )
        answer = await OfflinePlanner().respond(messages)
        value = answer.tool_calls[0]["name"] if answer.tool_calls else "direct"
        return Decision(
            {},
            choices={
                q.name: Selection(value, 1, {o.value: float(o.value == value) for o in q.choices})
                for q in questions
                if isinstance(q, Choice)
            },
        )


@dataclass
class CallBudget:
    maximum: int
    calls: int = 0

    def take(self) -> None:
        if self.calls >= self.maximum:
            message = "Model call budget exhausted"
            raise RuntimeError(message)
        self.calls += 1


@dataclass
class Usage:
    text_calls: int = 0
    decision_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    decision_input_tokens: int = 0
    unknown: int = 0

    def text(self, answer: AIMessage) -> None:
        if answer.usage_metadata is None:
            self.unknown += 1
        else:
            self.input_tokens += answer.usage_metadata["input_tokens"]
            self.output_tokens += answer.usage_metadata["output_tokens"]

    def snapshot(self) -> dict[str, int]:
        return dict(vars(self))


class ObservedText:
    def __init__(
        self,
        delegate: Planner,
        final: Callable[[list[AnyMessage]], Awaitable[AIMessage]],
        usage: Usage,
        budget: CallBudget,
        paid: bool,
    ) -> None:
        self.delegate, self.final = delegate, final
        self.usage, self.budget, self.paid = usage, budget, paid

    async def _call(self, messages: list[AnyMessage], final: bool) -> AIMessage:
        if self.paid:
            self.budget.take()
        self.usage.text_calls += 1
        try:
            answer = await (self.final(messages) if final else self.delegate.respond(messages))
        except BaseException:
            self.usage.unknown += 1
            raise
        if self.paid:
            self.usage.text(answer)
        return answer

    async def respond(self, messages: list[AnyMessage]) -> AIMessage:
        return await self._call(messages, False)

    async def respond_final(self, messages: list[AnyMessage]) -> AIMessage:
        return await self._call(messages, True)


class ObservedDecider:
    def __init__(self, delegate: Decider, usage: Usage, budget: CallBudget, paid: bool) -> None:
        self.delegate, self.usage, self.budget, self.paid = delegate, usage, budget, paid

    async def decide(self, text: str, questions: tuple[Question, ...]) -> Decision:
        if self.paid:
            self.budget.take()
        self.usage.decision_calls += 1
        try:
            answer = await self.delegate.decide(text, questions)
        except BaseException:
            self.usage.unknown += 1
            raise
        self.usage.decision_input_tokens += answer.input_tokens
        return answer

    async def aclose(self) -> None:
        await self.delegate.aclose()


@dataclass
class StepCounter:
    delegate: Planner
    tools: list[str] = field(default_factory=list)
    steps: int = 0

    async def respond(self, messages: list[AnyMessage]) -> AIMessage:
        self.steps += 1
        answer = await self.delegate.respond(messages)
        self.tools.extend(call["name"] for call in answer.tool_calls)
        return answer


def estimate(
    usage: dict[str, int],
    paid: bool,
    input_rate: float | None,
    output_rate: float | None,
    decision_rate: float,
) -> float | None:
    if not paid:
        return 0.0
    if usage["unknown"] or (usage["text_calls"] and (input_rate is None or output_rate is None)):
        return None
    return (
        usage["input_tokens"] * (input_rate or 0)
        + usage["output_tokens"] * (output_rate or 0)
        + usage["decision_input_tokens"] * decision_rate
    ) / 1_000_000


async def compare_planners(
    cases: list[dict[str, Any]],
    *,
    paid: bool = False,
    key: str = "",
    model: str = "gpt-4.1-mini",
    maximum: int = 0,
    input_rate: float | None = None,
    output_rate: float | None = None,
    decision_rate: float = 0.1,
) -> dict[str, Any]:
    from .worker_eval import metadata, score

    budget = CallBudget(maximum)
    reports: dict[str, Any] = {}
    question_fingerprint = ""
    for name in ("openai", "decisions"):
        text: OpenAIPlanner | OfflinePlanner = (
            OpenAIPlanner(key, model) if paid else OfflinePlanner()
        )
        final = text.respond_final if isinstance(text, OpenAIPlanner) else text.respond
        usage = Usage()
        observed = ObservedText(text, final, usage, budget, paid)
        decider: Decider = (
            OpenAIDecider(key) if paid and name == "decisions" else ScriptedChoiceDecider()
        )
        planner: Planner = (
            DecisionsPlanner(
                ObservedDecider(decider, usage, budget, paid), observed.respond_final, observed
            )
            if name == "decisions"
            else observed
        )
        if isinstance(planner, DecisionsPlanner):
            question_fingerprint = hashlib.sha256(
                json.dumps(asdict(planner.question), sort_keys=True).encode()
            ).hexdigest()
        rows: list[dict[str, Any]] = []
        try:
            for case in cases:
                if not paid and not case["offline"]:
                    rows.append({"id": case["id"], "status": "skipped"})
                    continue
                before = usage.snapshot()
                counter = StepCounter(planner)
                started = time.perf_counter()
                status, answer_text, source_ids = "failed", "", []
                try:
                    async with asyncio.timeout(45):
                        result = await LangGraphWorker(counter, 4).delegate_task(
                            case["goal"], case["context"]
                        )
                    status = result.status
                    answer_text = truncate(result.text, 120, max_bytes=500)
                    source_ids = [source.id for source in result.sources]
                except Exception as exc:
                    status = type(exc).__name__
                elapsed = time.perf_counter() - started
                delta = {k: v - before[k] for k, v in usage.snapshot().items()}
                output = {
                    "text": answer_text,
                    "status": status,
                    "source_ids": source_ids,
                    "tools": counter.tools,
                }
                expected = case["expected"].get("tool")
                rows.append(
                    {
                        "id": case["id"],
                        "status": status,
                        "output": output,
                        "steps": counter.steps,
                        "worker_seconds": elapsed,
                        "usage": delta,
                        "tool_selection_correct": float(
                            status == "completed" and counter.tools[:1] == [expected]
                        )
                        if expected
                        else None,
                        "plumbing": score(case, output),
                        "estimated_cost_usd": estimate(
                            delta, paid, input_rate, output_rate, decision_rate
                        ),
                    }
                )
        finally:
            try:
                if isinstance(text, OpenAIPlanner):
                    await text.aclose()
            finally:
                await decider.aclose()
        executed = [row for row in rows if row["status"] != "skipped"]
        labelled = [row for row in executed if row["tool_selection_correct"] is not None]
        costs = [row["estimated_cost_usd"] for row in executed]
        reports[name] = {
            "rows": rows,
            "summary": {
                "executed": len(executed),
                "skipped": len(rows) - len(executed),
                "failed": sum(row["status"] != "completed" for row in executed),
                "tool_selection_accuracy": statistics.mean(
                    row["tool_selection_correct"] for row in labelled
                )
                if labelled
                else None,
                "labelled_cases": len(labelled),
                "mean_steps": statistics.mean(row["steps"] for row in executed)
                if executed
                else None,
                "p50_worker_seconds": statistics.median(row["worker_seconds"] for row in executed)
                if executed
                else None,
                "estimated_cost_usd": sum(costs)
                if all(cost is not None for cost in costs)
                else None,
            },
        }
    return {
        "metadata": {
            **metadata(
                "comparison-live" if paid else "comparison-offline",
                model if paid else "scripted-stand-ins",
                None,
            ),
            "measured_at": datetime.now(UTC).isoformat(),
            "decision_question_sha256": question_fingerprint,
            "decision_model": "gpt-6-luna" if paid else "scripted-choice",
            "rates_usd_per_million": {
                "text_input": input_rate,
                "text_output": output_rate,
                "decisions_input": decision_rate,
            },
            "cost_scope": (
                "Configured token estimate; excludes caching discounts, "
                "missing usage and billing adjustments."
            ),
        },
        "planners": reports,
        "summary": {
            "failed": sum(r["summary"]["failed"] for r in reports.values()),
            "judge_failures": 0,
            "model_calls": budget.calls,
            "max_model_calls": maximum,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "| Planner | Executed | Labelled selection accuracy | Mean steps | "
        "p50 worker seconds | Estimated USD |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, value in report["planners"].items():
        s = value["summary"]
        label = name + (
            " (scripted stand-in)" if report["metadata"]["mode"] == "comparison-offline" else ""
        )
        values = [
            s[key]
            for key in (
                "tool_selection_accuracy",
                "mean_steps",
                "p50_worker_seconds",
                "estimated_cost_usd",
            )
        ]
        cells = ["unknown" if v is None else f"{v:.6f}" for v in values]
        lines.append(f"| {label} | {s['executed']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
