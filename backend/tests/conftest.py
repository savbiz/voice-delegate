"""Shared offline test resources with explicit lifetime and scheduling controls."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import pytest
from fastapi import FastAPI
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeConnection, FakeProvider
from voice_delegate.providers.models import SessionConfig
from voice_delegate_agent.reference import WorkerResult


@pytest.fixture(autouse=True)
def guard_sockets(socket_disabled: None) -> None:
    """Keep the pytest-socket guard active even when tests are selected individually."""


class ASGIClientFactory(Protocol):
    def __call__(self, app: FastAPI) -> AbstractAsyncContextManager[httpx.AsyncClient]: ...


@pytest.fixture
def asgi_client() -> ASGIClientFactory:
    @asynccontextmanager
    async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost"
            ) as transport,
        ):
            yield transport

    return client


class PublicSettingsFactory(Protocol):
    def __call__(self, path: Path, **overrides: object) -> Settings: ...


@pytest.fixture
def public_settings() -> PublicSettingsFactory:
    def settings(path: Path, **overrides: object) -> Settings:
        data: dict[str, object] = {
            "environment": "production",
            "allowed_hosts": ["localhost", "127.0.0.1"],
            "public_demo": True,
            "allowed_origin": "https://demo.example",
            "quota_database": str(path / "quotas.sqlite3"),
            "invite_tokens": {"alice": "a" * 32, "bob": "b" * 32},
            "session_ttl_seconds": 10,
            "daily_sessions_per_user": 2,
            "daily_voice_seconds_per_user": 22,
            "daily_voice_seconds_global": 33,
        }
        data.update(overrides)
        return Settings.model_validate(data)

    return settings


class BlockingWorker:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.gate = asyncio.Event()
        self.calls = 0
        self.return_on_cancel = True

    async def delegate_task(self, goal: str, context: str) -> WorkerResult:
        self.calls += 1
        self.started.set()
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            if not self.return_on_cancel:
                raise
            return WorkerResult("STALE RESULT")
        return WorkerResult("done")


@pytest.fixture
def blocking_worker() -> BlockingWorker:
    return BlockingWorker()


class BlockingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.gate = asyncio.Event()

    async def connect(self, *, config: SessionConfig, offer_sdp: str) -> FakeConnection:
        self.started.set()
        await self.gate.wait()
        return await super().connect(config=config, offer_sdp=offer_sdp)


@pytest.fixture
def blocking_provider() -> BlockingProvider:
    return BlockingProvider()


@dataclass
class FakeClock:
    now: float = 1_700_000_000

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


async def eventually(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.001)
