"""Shared scheduling helpers for backend and evaluation tests."""

import asyncio
from collections.abc import Callable


async def eventually(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.001)
