"""Application-owned planner clients shared by local and private worker factories."""

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
from voice_delegate_agent.tools import TOOLS
from voice_delegate_agent.web_search import TavilySearch

from voice_delegate.config import Settings
from voice_delegate.decisions.openai import OpenAIDecider


@dataclass
class PlannerRuntime:
    planner: Planner
    model: OpenAIPlanner | None = None
    decider: OpenAIDecider | None = None
    web: TavilySearch | None = None
    tools: tuple[BaseTool, ...] = tuple(TOOLS)
    instructions: str = INSTRUCTIONS

    def worker(self, max_steps: int) -> LangGraphWorker:
        return LangGraphWorker(
            self.planner, max_steps, tools=self.tools, instructions=self.instructions
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
                if self.web is not None:
                    await self.web.aclose()


def build_planner(settings: Settings) -> PlannerRuntime:
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
    instructions = worker_instructions(settings.web_search)
    if settings.worker_mode == "offline":
        return PlannerRuntime(
            OfflinePlanner(web_search=settings.web_search),
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
