"""Application-owned planner clients shared by local and private worker factories."""

import os
from dataclasses import dataclass

from langchain_core.tools import BaseTool
from voice_delegate_agent.graph import (
    INSTRUCTIONS,
    DecisionsPlanner,
    LangGraphWorker,
    OfflinePlanner,
    OpenAIPlanner,
    Planner,
    worker_instructions,
)
from voice_delegate_agent.mcp import McpRegistry, McpServer
from voice_delegate_agent.moderation import Moderator, Origin, PolicyModerator, Verdict
from voice_delegate_agent.tools import TOOLS
from voice_delegate_agent.web_search import TavilySearch

from voice_delegate.config import Settings
from voice_delegate.decisions.openai import OpenAIDecider
from voice_delegate.moderation import DecisionsClassifier
from voice_delegate.observability.metrics import Metrics


@dataclass
class PlannerRuntime:
    planner: Planner
    model: OpenAIPlanner | None = None
    decider: OpenAIDecider | None = None
    web: TavilySearch | None = None
    tools: tuple[BaseTool, ...] = tuple(TOOLS)
    instructions: str = INSTRUCTIONS
    moderator: Moderator | None = None
    classifier: DecisionsClassifier | None = None
    max_reviews: int = 6
    mcp: McpRegistry | None = None

    def worker(self, max_steps: int) -> LangGraphWorker:
        return LangGraphWorker(
            self.planner,
            max_steps,
            tools=self.tools,
            instructions=self.instructions,
            moderator=self.moderator,
            max_reviews=self.max_reviews,
            mcp=self.mcp,
        )

    async def aclose(self) -> None:
        try:
            if self.model is not None:
                await self.model.aclose()
        finally:
            try:
                if self.decider is not None:
                    await self.decider.aclose()
            finally:
                try:
                    if self.web is not None:
                        await self.web.aclose()
                finally:
                    try:
                        if self.mcp is not None:
                            await self.mcp.aclose()
                    finally:
                        if self.classifier is not None:
                            await self.classifier.aclose()


def build_planner(settings: Settings, metrics: Metrics | None = None) -> PlannerRuntime:
    runtime = _build_planner(settings)
    runtime.mcp = _build_mcp(settings)
    if not settings.moderation:
        return runtime
    decider = runtime.decider
    classifier = DecisionsClassifier(
        decider or OpenAIDecider(settings.openai_api_key.get_secret_value()),
        timeout=settings.moderation_timeout_seconds,
        owns=decider is None,
    )

    def record(origin: Origin, verdict: Verdict) -> None:
        if metrics is not None:
            metrics.moderation_reviews.add(
                1,
                {"origin": origin.value, "action": verdict.action.value, "reason": verdict.reason},
            )

    runtime.classifier = classifier
    runtime.max_reviews = settings.moderation_max_reviews
    runtime.moderator = PolicyModerator(
        classifier, threshold=settings.moderation_threshold, on_review=record
    )
    return runtime


def _build_mcp(settings: Settings) -> McpRegistry | None:
    """Fail at startup when an audited server's credential variable is missing."""
    if not settings.mcp_servers:
        return None
    servers = []
    for entry in settings.mcp_servers:
        token = os.environ.get(entry.token_env, "") if entry.token_env else ""
        if entry.token_env and not token:
            message = f"MCP server {entry.id} needs the {entry.token_env} variable"
            raise ValueError(message)
        servers.append(McpServer(entry.id, entry.url, tuple(entry.tools), token))
    return McpRegistry(
        tuple(servers), timeout=settings.mcp_timeout_seconds, ttl=settings.mcp_cache_seconds
    )


def _build_planner(settings: Settings) -> PlannerRuntime:
    web = (
        TavilySearch(
            settings.tavily_api_key.get_secret_value(),
            domains=tuple(settings.web_search_domains),
            timeout=settings.web_search_timeout_seconds,
        )
        if settings.web_search
        else None
    )
    tools = (*TOOLS, web.tool()) if web is not None else tuple(TOOLS)
    mcp = bool(settings.mcp_servers)
    instructions = worker_instructions(settings.web_search, mcp)
    if settings.worker_mode == "offline":
        return PlannerRuntime(
            OfflinePlanner(web_search=settings.web_search, mcp=mcp),
            web=web,
            tools=tools,
            instructions=instructions,
        )
    model = (
        OpenAIPlanner(
            settings.openai_api_key.get_secret_value(), settings.worker_model, tools=tools
        )
        if web is not None
        else OpenAIPlanner(settings.openai_api_key.get_secret_value(), settings.worker_model)
    )
    if settings.worker_mode == "openai":
        return PlannerRuntime(model, model, web=web, tools=tools, instructions=instructions)
    decider = OpenAIDecider(
        settings.openai_api_key.get_secret_value(), timeout=settings.decisions_timeout_seconds
    )
    return PlannerRuntime(
        DecisionsPlanner(
            decider,
            model.respond_final,
            model,
            timeout=settings.decisions_timeout_seconds,
            tools=tools,
            instructions=instructions,
        ),
        model,
        decider,
        web,
        tools,
        instructions,
    )
