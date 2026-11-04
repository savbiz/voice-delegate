"""A bounded model/tool loop; planners live in `planners.py` and are re-exported here."""

import contextlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict
from html import escape
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from .limits import SOURCE_PREVIEW_CHARS
from .mcp import McpRegistry, job_tools, use_job_tools, verified_mcp_source
from .moderation import Action, Moderator, Origin, Reason, Verdict, failure_verdict
from .planners import INSTRUCTIONS, DecisionsPlanner, OfflinePlanner, OpenAIPlanner, Planner
from .prompts import worker_prompt
from .reference import Source, WorkerResult, source_by_id
from .tools import TOOLS
from .web_search import verified_web_source

__all__ = [
    "INSTRUCTIONS",
    "DecisionsPlanner",
    "LangGraphWorker",
    "OfflinePlanner",
    "OpenAIPlanner",
    "Planner",
    "worker_instructions",
]


def worker_instructions(web_search: bool = False, mcp: bool = False) -> str:
    return worker_prompt(web_search=web_search, mcp=mcp)


class State(TypedDict):
    """Per-invocation state; no memory or checkpoint shared across sessions."""

    messages: Annotated[list[AnyMessage], add_messages]
    steps: int
    source_ids: list[str]
    latest_source_ids: list[str]
    failed: bool
    evidence: dict[str, Source]
    web_seen: bool
    web_unavailable: bool
    mcp_seen: bool
    mcp_unavailable: bool
    reviews: int


EVIDENCE_ORIGINS = {
    "search_documentation": Origin.DOCUMENTATION,
    "web_search": Origin.WEB,
}
# Arithmetic output is a bounded number produced by the evaluator, not external text.
UNMODERATED_TOOLS = {"calculate"}
REFUSALS = {
    Reason.UNAVAILABLE: "Moderation unavailable; task was not started.",
    Reason.BUDGET: "Moderation budget exhausted; task was not started.",
    Reason.OVERSIZE: "Request too long to review; task was not started.",
}


class LangGraphWorker:
    """Run one goal through finite model/tool steps and return plain text."""

    def __init__(
        self,
        planner: Planner,
        max_steps: int = 4,
        *,
        tools: Sequence[BaseTool] | None = None,
        instructions: str = INSTRUCTIONS,
        moderator: Moderator | None = None,
        max_reviews: int = 6,
        mcp: McpRegistry | None = None,
    ) -> None:
        self.planner = planner
        self.mcp = mcp
        self.max_steps = max_steps
        self.moderator = moderator
        self.max_reviews = max_reviews
        registry = {tool.name: tool for tool in (TOOLS if tools is None else tools)}
        self.instructions = instructions

        async def reason(state: State) -> dict[str, object]:
            if state["steps"] >= self.max_steps:
                return {
                    "messages": [AIMessage(content="Worker step limit reached; task incomplete.")],
                    "failed": True,
                }
            answer = await self.planner.respond(state["messages"])
            if (state["web_seen"] or state["mcp_seen"]) and answer.tool_calls:
                return {
                    "messages": [
                        AIMessage(
                            content="Worker rejected tool calls after "
                            + ("web" if state["web_seen"] else "tool")
                            + " evidence; task incomplete."
                        )
                    ],
                    "failed": True,
                    "steps": state["steps"] + 1,
                }
            return {
                "messages": [answer],
                "steps": state["steps"] + 1,
                "failed": state["failed"] or answer.response_metadata.get("worker_failed") is True,
            }

        async def review(origin: Origin, text: str, used: int) -> Verdict:
            if self.moderator is None:
                return Verdict(Action.ALLOW, Reason.OK)
            if used >= self.max_reviews:
                return failure_verdict(origin, Reason.BUDGET)
            return await self.moderator.review(origin, text)

        async def execute(state: State) -> dict[str, object]:
            answer = state["messages"][-1]
            if not isinstance(answer, AIMessage):
                message = "Tool execution requires an AIMessage"
                raise ValueError(message)  # noqa: TRY004 - explicit worker boundary contract
            if len(answer.tool_calls) != 1:
                return {
                    "messages": [
                        AIMessage(content="Worker rejected parallel tool calls; task incomplete.")
                    ],
                    "failed": True,
                }
            call = answer.tool_calls[0]
            extra = {t.name: t for t in job_tools()}
            tool = registry.get(call["name"]) or extra.get(call["name"])
            web_call = tool is not None and call["name"] == "web_search"
            mcp_call = call["name"] in extra
            failed = state.get("failed", False) or tool is None
            try:
                result = (
                    await tool.ainvoke(call["args"]) if tool else "Unknown tool; no action taken."
                )
            except ValidationError:
                failed = True
                result = "Tool input invalid; no action taken."
            except Exception:
                failed = True
                result = "Tool failed; no action taken."
            reviews = state["reviews"]
            if self.moderator is not None and call["name"] not in UNMODERATED_TOOLS:
                origin = EVIDENCE_ORIGINS.get(call["name"], Origin.MCP)
                verdict = await review(origin, str(result), reviews)
                reviews += 1
                if not verdict.allowed:
                    # Withheld text never reaches the planner, citations or narration.
                    return {
                        "messages": [
                            AIMessage(
                                content="Tool evidence was withheld by moderation; task incomplete."
                            )
                        ],
                        "failed": True,
                        "reviews": reviews,
                        "web_seen": state["web_seen"] or web_call,
                        "mcp_seen": state["mcp_seen"] or mcp_call,
                    }
            source_ids = list(state["source_ids"])
            evidence = dict(state["evidence"])
            web_unavailable = state["web_unavailable"]
            mcp_unavailable = state["mcp_unavailable"]
            latest_source_ids = state["latest_source_ids"]
            if call["name"] == "search_documentation" or web_call or mcp_call:
                latest_source_ids = []
                with contextlib.suppress(ValueError, KeyError, TypeError):
                    payload = json.loads(str(result))
                    if web_call:
                        web_unavailable = payload.get("status") == "web_unavailable"
                    if mcp_call:
                        mcp_unavailable = payload.get("status") == "mcp_unavailable"
                        failed = failed or mcp_unavailable
                    checked = []
                    for entry in payload["sources"][:3]:
                        identity = entry["id"]
                        source = source_by_id(identity)
                        if source is None and (web_call or mcp_call):
                            candidate = Source(**entry)
                            verify = verified_web_source if web_call else verified_mcp_source
                            source = candidate if verify(candidate) else None
                        if source is not None:
                            evidence.setdefault(identity, source)
                            if identity not in source_ids:
                                source_ids.append(identity)
                            latest_source_ids.append(identity)
                            checked.append(
                                {
                                    **asdict(evidence[identity]),
                                    "text": evidence[identity].text[:SOURCE_PREVIEW_CHARS],
                                    "citation": source_ids.index(identity) + 1,
                                }
                            )
                    payload["sources"] = checked
                    result = json.dumps(payload, ensure_ascii=False)
            return {
                "messages": [ToolMessage(content=str(result), tool_call_id=call["id"])],
                "source_ids": source_ids,
                "failed": failed,
                "latest_source_ids": latest_source_ids,
                "evidence": evidence,
                "web_seen": state["web_seen"] or web_call,
                "web_unavailable": web_unavailable,
                "mcp_seen": state["mcp_seen"] or mcp_call,
                "mcp_unavailable": mcp_unavailable,
                "reviews": reviews,
            }

        def route(state: State) -> Literal["tools", "__end__"]:
            answer = state["messages"][-1]
            return "tools" if isinstance(answer, AIMessage) and answer.tool_calls else "__end__"

        def after_tool(state: State) -> Literal["reason", "__end__"]:
            return "reason" if isinstance(state["messages"][-1], ToolMessage) else "__end__"

        builder = StateGraph(State)
        builder.add_node("reason", reason)
        builder.add_node("tools", execute)
        builder.add_edge(START, "reason")
        builder.add_conditional_edges("reason", route)
        builder.add_conditional_edges("tools", after_tool)
        self.graph = builder.compile()

    async def delegate_task(self, goal: str, context: str) -> WorkerResult:
        """Process a bounded request without retaining transcript state."""
        reviews = 0
        if self.moderator is not None:
            verdict = await self.moderator.review(Origin.USER, goal)
            reviews = 1
            if not verdict.allowed:
                return WorkerResult(
                    REFUSALS.get(
                        verdict.reason, "I cannot help with that request; no action taken."
                    ),
                    status="failed" if verdict.reason in REFUSALS else "completed",
                )
        extra = await self.mcp.snapshot() if self.mcp is not None else ()
        with use_job_tools(extra):
            result = await self.graph.ainvoke(
                {
                    "messages": [
                        SystemMessage(content=self.instructions),
                        HumanMessage(
                            content=f"<goal>{escape(goal)}</goal>\n<context>{escape(context)}</context>"
                        ),
                    ],
                    "steps": 0,
                    "failed": False,
                    "source_ids": [],
                    "latest_source_ids": [],
                    "evidence": {},
                    "web_seen": False,
                    "web_unavailable": False,
                    "mcp_seen": False,
                    "mcp_unavailable": False,
                    "reviews": reviews,
                },
                config={"recursion_limit": self.max_steps * 2 + 3, "callbacks": []},
            )
        last = result["messages"][-1]
        answer = (
            str(last.content)
            if isinstance(last.content, str)
            else "Worker returned non-text output."
        )
        identities = result["source_ids"]
        citations = list(dict.fromkeys(int(n) for n in re.findall(r"\[(\d+)\]", answer)))
        if result["mcp_seen"] and not result["failed"] and identities and not citations:
            return WorkerResult(
                "Tool answer lacks verified citations; task incomplete.", status="failed"
            )
        if (
            result["mcp_seen"]
            and not result["web_seen"]
            and not result["failed"]
            and not identities
        ):
            return WorkerResult("No supporting tool results found.")
        if result["web_seen"] and not result["failed"] and identities and not citations:
            return WorkerResult(
                "Web answer lacks verified citations; task incomplete.", status="failed"
            )
        if result["web_seen"] and not result["failed"] and not identities:
            return WorkerResult(
                "Web search unavailable; no supporting project documentation found."
                if result["web_unavailable"]
                else "No supporting web results found."
            )
        if len(citations) > 3 or any(index < 1 or index > len(identities) for index in citations):
            return WorkerResult(
                "Worker citations could not be verified; task incomplete.", status="failed"
            )
        if result["web_unavailable"] and not result["failed"]:
            notice = "Web search unavailable; using bundled project documentation only."
            if not answer.startswith(notice):
                answer = notice + " " + answer
        selected = list(
            dict.fromkeys(
                [identities[index - 1] for index in citations] + result["latest_source_ids"]
            )
        )[:3]
        answer = re.sub(
            r"\[(\d+)\]",
            lambda match: f"[{selected.index(identities[int(match[1]) - 1]) + 1}]",
            answer,
        )
        sources = tuple(
            source
            for identity in selected
            if (source := result["evidence"].get(identity) or source_by_id(identity)) is not None
        )
        failed = result["failed"] or not isinstance(last.content, str)
        return WorkerResult(answer, sources, "failed" if failed else "completed")
