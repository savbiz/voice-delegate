"""Worker client; creation is never retried and cancellation uses the preallocated ID."""

import asyncio
import time
from contextlib import suppress
from uuid import uuid4

import httpx
from voice_delegate_agent.reference import WorkerResult, source_by_id
from voice_delegate_agent.usage import Usage, note

from voice_delegate.config import Settings, worker_transport_allowed
from voice_delegate.delegation.contracts import WorkerBusy
from voice_delegate.session.access import PersonalKeys

from .worker_service import JobOutput


class RemoteWorker:
    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
        personal_keys: PersonalKeys | None = None,
    ) -> None:
        if personal_keys is not None and not worker_transport_allowed(settings.worker_service_url):
            message = "Personal worker keys require a private transport or HTTPS"
            raise ValueError(message)
        self.settings = settings
        self.personal_keys = personal_keys
        self.http = http or httpx.AsyncClient(
            trust_env=False, timeout=3, limits=httpx.Limits(max_connections=16)
        )
        self.base = settings.worker_service_url.rstrip("/")
        self.headers = {
            "Authorization": "Bearer " + settings.worker_service_token.get_secret_value()
        }

    async def delegate_task(self, goal: str, context: str) -> WorkerResult:
        received_usage = False
        key = str(uuid4())
        url = f"{self.base}/jobs/{key}"
        try:
            response = await self.http.post(
                self.base + ("/personal-jobs" if self.personal_keys is not None else "/jobs"),
                headers=self.headers,
                json={
                    "request_id": key,
                    "goal": goal,
                    "context": context,
                    "deadline": time.time() + self.settings.delegation_timeout_seconds,
                    **(
                        {
                            "personal_keys": {
                                "openai_key": self.personal_keys.openai_key.get_secret_value(),
                                "tavily_key": self.personal_keys.tavily_key.get_secret_value(),
                            }
                        }
                        if self.personal_keys is not None
                        else {}
                    ),
                },
            )
            if response.status_code == 429:
                message = "Worker capacity reached"
                raise WorkerBusy(message)
            response.raise_for_status()
            while True:
                response = await self.http.get(url, headers=self.headers)
                response.raise_for_status()
                result = JobOutput.model_validate_json(response.content)
                if result.status != "running":
                    note(result.usage)
                    received_usage = True
                if result.status == "completed" or (result.status == "failed" and result.text):
                    if result.web_sources and not self.settings.web_search:
                        message = "Remote worker web evidence was not enabled"
                        raise RuntimeError(message)
                    web = {s.id: s for s in result.web_sources} if self.settings.web_search else {}
                    sources = tuple(
                        s
                        for key in result.source_ids
                        if (s := source_by_id(key) or web.get(key)) is not None
                    )
                    return WorkerResult(
                        result.text, sources, "failed" if result.status == "failed" else "completed"
                    )
                if result.status != "running":
                    message = "Remote worker did not complete"
                    raise RuntimeError(message)
                await asyncio.sleep(0.2)
        finally:
            if not received_usage:
                note(Usage(uncertain=True))
            # Tombstone even after ambiguous POST failures; never resubmit this task.
            with suppress(httpx.HTTPError, TimeoutError):
                async with asyncio.timeout(3):
                    await self.http.delete(url, headers=self.headers)

    async def aclose(self) -> None:
        self.personal_keys = None
        await self.http.aclose()
