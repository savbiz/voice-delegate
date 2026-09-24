"""Private bounded worker service: no retries, ephemeral jobs and cancellation tombstones."""

import asyncio
import hashlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from secrets import compare_digest
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner, OpenAIPlanner

from voice_delegate.config import Settings, load_settings
from voice_delegate.delegation.contracts import Worker
from voice_delegate.limits.http import BodyLimitMiddleware
from voice_delegate.limits.tokens import truncate


class JobInput(BaseModel):
    request_id: UUID
    goal: str = Field(min_length=1, max_length=8192)
    context: str = Field(default="", max_length=32768)
    deadline: float = Field(allow_inf_nan=False)


class JobOutput(BaseModel):
    status: str
    text: str = ""
    source_ids: tuple[str, ...] = ()


@dataclass
class Job:
    fingerprint: str
    expires: float
    task: asyncio.Task[None] | None = None
    status: str = "running"
    text: str = ""
    source_ids: tuple[str, ...] = ()


class Jobs:
    def __init__(self, worker: Worker, settings: Settings) -> None:
        self.worker = worker
        self.settings = settings
        self.items: dict[UUID, Job] = {}

    def sweep(self) -> None:
        now = time.time()
        for key, job in list(self.items.items()):
            if job.expires <= now:
                if job.task is not None and not job.task.done():
                    job.task.cancel()
                else:
                    del self.items[key]

    def cancel(self, key: UUID) -> None:
        self.sweep()
        job = self.items.get(key)
        if job is None:
            if len(self.items) >= self.settings.worker_max_records:
                raise HTTPException(503, "Worker cancellation ledger full")
            job = Job("", time.time() + 180)
            self.items[key] = job
        job.status = "cancelled"
        job.text, job.source_ids = "", ()
        if job.task is not None:
            job.task.cancel()

    def start(self, body: JobInput) -> Job:
        self.sweep()
        now = time.time()
        if not now < body.deadline <= now + 120:
            raise HTTPException(422, "Job deadline expired or exceeds maximum lifetime")
        fingerprint = hashlib.sha256((body.goal + "\0" + body.context).encode()).hexdigest()
        if body.request_id in self.items:
            job = self.items[body.request_id]
            if job.fingerprint and job.fingerprint != fingerprint:
                raise HTTPException(409, "Request identifier already used")
            return job
        active = sum(job.task is not None and not job.task.done() for job in self.items.values())
        if (
            active >= self.settings.worker_service_capacity
            or len(self.items) >= self.settings.worker_max_records
        ):
            raise HTTPException(429, "Worker capacity reached; job not queued")
        job = Job(fingerprint, now + 180)
        self.items[body.request_id] = job
        job.task = asyncio.create_task(self.run(job, body), name="remote-delegation")
        return job

    async def run(self, job: Job, body: JobInput) -> None:
        try:
            async with asyncio.timeout(
                min(
                    self.settings.delegation_timeout_seconds,
                    max(0.001, body.deadline - time.time()),
                )
            ):
                result = await self.worker.delegate_task(body.goal, body.context)
            if job.status != "cancelled":
                job.text = truncate(
                    result.text, self.settings.delegation_result_tokens, max_bytes=500
                )
                job.source_ids = tuple(s.id for s in result.sources)
                job.status = "completed"
        except asyncio.CancelledError:
            job.status = "cancelled"
            raise
        except TimeoutError:
            job.status = "timeout"
        except Exception:
            job.status = "failed"

    async def aclose(self) -> None:
        tasks = [job.task for job in self.items.values() if job.task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=1)
        self.items.clear()


def create_worker_app(settings: Settings | None = None, worker: Worker | None = None) -> FastAPI:
    settings = settings or load_settings()
    if len(settings.worker_service_token.get_secret_value()) < 32:
        message = "Private worker service requires a token of at least 32 characters"
        raise ValueError(message)
    planner = None
    if worker is None:
        planner = (
            OpenAIPlanner(settings.openai_api_key.get_secret_value(), settings.worker_model)
            if settings.worker_mode == "openai"
            else OfflinePlanner()
        )
        worker = LangGraphWorker(planner, settings.worker_max_steps)
    jobs = Jobs(worker, settings)

    async def janitor() -> None:
        while True:
            try:
                await asyncio.sleep(1)
                jobs.sweep()
            except Exception:
                logging.getLogger(__name__).exception("Worker janitor failed; retrying")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        sweep = asyncio.create_task(janitor())
        try:
            yield
        finally:
            sweep.cancel()
            with suppress(asyncio.CancelledError):
                await sweep
            await jobs.aclose()
            if isinstance(planner, OpenAIPlanner):
                await planner.aclose()

    async def authorized(authorization: str = Header(default="")) -> None:
        expected = "Bearer " + settings.worker_service_token.get_secret_value()
        if not compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "Private worker authentication required")

    app = FastAPI(lifespan=lifespan, dependencies=[Depends(authorized)])
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)

    @app.post("/jobs", status_code=202)
    async def start(body: JobInput) -> JobOutput:
        job = jobs.start(body)
        return JobOutput(status=job.status)

    @app.get("/jobs/{key}")
    async def result(key: UUID) -> JobOutput:
        jobs.sweep()
        job = jobs.items.get(key)
        if job is None:
            raise HTTPException(404, "Job not found or expired")
        return JobOutput(status=job.status, text=job.text, source_ids=job.source_ids)

    @app.delete("/jobs/{key}")
    async def cancel(key: UUID) -> JobOutput:
        jobs.cancel(key)
        return JobOutput(status="cancelled")

    return app
