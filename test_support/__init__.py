"""Shared scheduling helpers for backend and evaluation tests."""

import asyncio
from collections.abc import Callable

from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner
from voice_delegate_agent.reference import WorkerResult


async def eventually(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.001)


class CountingWorker:
    """Count actual worker invocations while retaining deterministic tool execution."""

    def __init__(self) -> None:
        self.calls = 0

    async def delegate_task(self, goal: str, context: str) -> WorkerResult:
        self.calls += 1
        return await LangGraphWorker(OfflinePlanner()).delegate_task(goal, context)
