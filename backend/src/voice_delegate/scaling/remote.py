"""Worker client; creation is never retried and cancellation uses the preallocated ID."""

import asyncio
import time
from contextlib import suppress
from uuid import uuid4

import httpx
from voice_delegate_agent.reference import GroundedAnswer, source_by_id

from voice_delegate.config import Settings
from voice_delegate.delegation.contracts import WorkerBusy

from .worker_service import JobOutput


class RemoteWorker:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.http = http or httpx.AsyncClient(timeout=3, limits=httpx.Limits(max_connections=16))
        self.base = settings.worker_service_url.rstrip("/")
        self.headers = {
            "Authorization": "Bearer " + settings.worker_service_token.get_secret_value()
        }

    async def delegate_task(self, goal: str, context: str) -> str:
        key = str(uuid4())
        url = f"{self.base}/jobs/{key}"
        try:
            response = await self.http.post(
                self.base + "/jobs",
                headers=self.headers,
                json={
                    "request_id": key,
                    "goal": goal,
                    "context": context,
                    "deadline": time.time() + self.settings.delegation_timeout_seconds,
                },
            )
            if response.status_code == 429:
                raise WorkerBusy("Worker capacity reached")
            response.raise_for_status()
            while True:
                response = await self.http.get(url, headers=self.headers)
                response.raise_for_status()
                result = JobOutput.model_validate_json(response.content)
                if result.status == "completed":
                    sources = tuple(
                        s for key in result.source_ids if (s := source_by_id(key)) is not None
                    )
                    return GroundedAnswer(result.text, sources) if sources else result.text
                if result.status != "running":
                    raise RuntimeError("Remote worker did not complete")
                await asyncio.sleep(0.05)
        finally:
            # Tombstone even after ambiguous POST failures; never resubmit this task.
            with suppress(httpx.HTTPError, TimeoutError):
                async with asyncio.timeout(3):
                    await self.http.delete(url, headers=self.headers)

    async def aclose(self) -> None:
        await self.http.aclose()
