"""Single application delegation contract shared by voice adapters and workers."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class DelegationInput(BaseModel):
    """Untrusted goal and transcript context, separate from worker instructions."""

    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, max_length=8192)
    context: str = Field(default="", max_length=32768)


DELEGATE_TOOL = {
    "type": "function",
    "name": "delegate_task",
    "description": "Delegate arithmetic or a project-reference lookup to the worker.",
    "parameters": DelegationInput.model_json_schema(),
}


class Worker(Protocol):
    """Workers must cooperate with asyncio cancellation and avoid blocking I/O."""

    async def delegate_task(self, goal: str, context: str) -> str:
        """Return compact factual text; never change live session instructions."""
        ...
