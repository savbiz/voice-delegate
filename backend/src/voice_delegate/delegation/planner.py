"""Application-owned planner clients shared by local and private worker factories."""

from dataclasses import dataclass

from voice_delegate_agent.graph import DecisionsPlanner, OfflinePlanner, OpenAIPlanner, Planner

from voice_delegate.config import Settings
from voice_delegate.decisions.openai import OpenAIDecider


@dataclass
class PlannerRuntime:
    planner: Planner
    model: OpenAIPlanner | None = None
    decider: OpenAIDecider | None = None

    async def aclose(self) -> None:
        try:
            if self.model is not None:
                await self.model.aclose()
        finally:
            if self.decider is not None:
                await self.decider.aclose()


def build_planner(settings: Settings) -> PlannerRuntime:
    if settings.worker_mode == "offline":
        return PlannerRuntime(OfflinePlanner())
    model = OpenAIPlanner(settings.openai_api_key.get_secret_value(), settings.worker_model)
    if settings.worker_mode == "openai":
        return PlannerRuntime(model, model)
    decider = OpenAIDecider(
        settings.openai_api_key.get_secret_value(), timeout=settings.decisions_timeout_seconds
    )
    return PlannerRuntime(
        DecisionsPlanner(
            decider, model.respond_final, model, timeout=settings.decisions_timeout_seconds
        ),
        model,
        decider,
    )
