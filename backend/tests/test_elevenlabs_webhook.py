"""Provider-owned webhook requests never need browser tool callbacks or result polling."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import pytest
from conftest import FakeClock
from fastapi import FastAPI
from pydantic import SecretStr
from starlette.types import Message
from voice_delegate.api.elevenlabs_webhook import build_webhook_router
from voice_delegate.api.routes import build_router
from voice_delegate.config import Settings
from voice_delegate.limits.http import BodyLimitMiddleware
from voice_delegate.providers.elevenlabs_session import ElevenLabsConnection
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import Session
from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner
from voice_delegate_agent.reference import WorkerResult

from test_support import eventually

TOKEN = "fixture-webhook-token-32-characters-long"
URL = "https://backend.example/integrations/elevenlabs/delegate"
PATH = "/integrations/elevenlabs/delegate"
HEADERS = {"X-Voice-Webhook-Token": TOKEN, "X-Voice-Conversation-Id": "conv_fixture"}


class Worker:
    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.gate.set()
        self.started = asyncio.Event()
        self.calls = 0

    async def delegate_task(self, goal: str, context: str) -> WorkerResult:
        self.calls += 1
        self.started.set()
        await self.gate.wait()
        return await LangGraphWorker(OfflinePlanner()).delegate_task(goal, context)


@dataclass
class Fixture:
    app: FastAPI
    client: httpx.AsyncClient
    manager: SessionManager
    session: Session
    connection: ElevenLabsConnection
    worker: Worker
    clock: FakeClock

    def quiet(self) -> None:
        state = self.session.portfolio
        self.manager.intent.activity(state, state.sequence + 1, speaking=False)
        self.clock.advance(0.7)
        self.manager.intent.activity(state, state.sequence + 1, speaking=False)


@pytest.fixture
async def fixture() -> AsyncIterator[Fixture]:
    clock = FakeClock()
    worker = Worker()
    settings = Settings(
        voice_provider="elevenlabs",
        intent_cancellation=True,
        elevenlabs_enabled=True,
        elevenlabs_api_key=SecretStr("fixture"),
        elevenlabs_agent_id="agent_fixture",
        elevenlabs_webhook_url=URL,
        elevenlabs_webhook_token=SecretStr(TOKEN),
    )
    manager = SessionManager(FakeProvider(), settings, clock=clock, worker=worker)
    session = manager.create()
    session.state = "connecting"

    async def confirm() -> bool:
        return False

    connection = ElevenLabsConnection("conv_fixture", confirm)
    session.connection = connection

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await manager.aclose()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(BodyLimitMiddleware, max_bytes=65536)
    app.include_router(build_router(manager))
    app.include_router(build_webhook_router(manager))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        yield Fixture(app, client, manager, session, connection, worker, clock)


async def test_server_response_waits_for_worker_and_quiet_without_browser_tools(
    fixture: Fixture,
) -> None:
    f = fixture
    response = asyncio.create_task(
        f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"})
    )
    await f.worker.started.wait()
    assert f.connection.started
    await eventually(lambda: any(j.status == "pending" for j in f.session.portfolio.jobs.values()))
    assert not response.done()
    f.manager.intent.activity(f.session.portfolio, 1, speaking=True)
    await asyncio.sleep(0.12)
    assert not response.done()
    f.quiet()
    result = await asyncio.wait_for(response, 2)
    assert result.status_code == 200 and "4" in result.json()["result"]
    assert result.headers["cache-control"] == "no-store"
    assert len(f.connection.calls) == 1 and f.worker.calls == 1
    # Replay returns the cached HTTP result; no invented native tool ID or second execution.
    replay = await f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"})
    assert replay.json() == result.json() and f.worker.calls == 1
    for suffix in ("delegate", "result"):
        assert (
            await f.client.post(
                f"/api/sessions/{f.session.id}/elevenlabs/{suffix}", json={"goal": "calculate 2+2"}
            )
        ).status_code == 404
    assert (await f.client.post("/api/config")).status_code == 403


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 401),
        ({**HEADERS, "X-Voice-Webhook-Token": "wrong"}, 401),
        ({**HEADERS, "X-Voice-Conversation-Id": "foreign"}, 404),
        ({**HEADERS, "Origin": "http://localhost:5173"}, 403),
    ],
)
async def test_service_auth_and_session_binding_reject_before_work(
    fixture: Fixture, headers: dict[str, str], status: int
) -> None:
    result = await fixture.client.post(PATH, headers=headers, json={"goal": "calculate 2+2"})
    assert result.status_code == status
    assert result.headers["cache-control"] == "no-store"
    assert fixture.worker.calls == 0
    assert not fixture.connection.calls


@pytest.mark.parametrize(
    "body", [{"goal": " "}, {"goal": "é" * 4097}, {"goal": "x", "session_id": "arbitrary"}]
)
async def test_webhook_body_is_bounded_and_cannot_select_an_owner(
    fixture: Fixture, body: object
) -> None:
    response = await fixture.client.post(PATH, headers=HEADERS, json=body)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "Invalid webhook request"}
    assert fixture.worker.calls == 0


async def test_duplicate_waiter_cancellation_preserves_work(fixture: Fixture) -> None:
    f = fixture
    f.worker.gate.clear()
    first = asyncio.create_task(
        f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"})
    )
    await f.worker.started.wait()
    second = asyncio.create_task(
        f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"})
    )
    await eventually(lambda: next(iter(f.connection.calls.values())).waiters == 2)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert f.worker.calls == 1
    assert next(iter(f.session.portfolio.jobs.values())).status == "running"
    f.worker.gate.set()
    f.quiet()
    assert "4" in (await asyncio.wait_for(second, 2)).json()["result"]


async def test_two_tasks_busy_rejection_and_targeted_cancel(fixture: Fixture) -> None:
    f = fixture
    f.worker.gate.clear()
    first = asyncio.create_task(
        f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"})
    )
    second = asyncio.create_task(
        f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 3+4"})
    )
    await eventually(lambda: f.worker.calls == 2)
    busy = await asyncio.wait_for(
        f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 5+6"}), 2
    )
    assert "busy" in busy.json()["result"].lower() and f.worker.calls == 2
    job = next(j for j in f.session.portfolio.jobs.values() if "3+4" in j.goal)
    f.manager.interrupt(f.session, task_id=job.id)
    assert "cancelled" in (await asyncio.wait_for(second, 2)).json()["result"]
    assert next(j for j in f.session.portfolio.jobs.values() if "2+2" in j.goal).status == "running"
    f.worker.gate.set()
    f.quiet()
    assert "4" in (await asyncio.wait_for(first, 2)).json()["result"]


async def test_session_end_settles_http_response_and_rejects_replay(fixture: Fixture) -> None:
    f = fixture
    f.worker.gate.clear()
    waiting = asyncio.create_task(
        f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"})
    )
    await f.worker.started.wait()
    await f.manager.close(f.session)
    assert "Session ended" in (await asyncio.wait_for(waiting, 2)).json()["result"]
    assert (
        await f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"})
    ).status_code == 404


async def test_waiter_limit_and_response_deadline_are_bounded(
    fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from voice_delegate.api import elevenlabs_webhook

    f = fixture
    f.worker.gate.clear()
    tasks = [
        asyncio.create_task(f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"}))
        for _ in range(4)
    ]
    await eventually(
        lambda: bool(f.connection.calls) and next(iter(f.connection.calls.values())).waiters == 4
    )
    assert (
        await f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"})
    ).status_code == 429
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert next(iter(f.connection.calls.values())).waiters == 0
    monkeypatch.setattr(elevenlabs_webhook, "WEBHOOK_TIMEOUT_SECONDS", 0.01)
    result = await asyncio.wait_for(
        f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 3+4"}), 2
    )
    assert "window expired" in result.json()["result"]
    assert len(f.connection.calls) == 2


async def test_default_application_has_no_service_ingress() -> None:
    from voice_delegate.api.app import create_app

    app = create_app(Settings(), FakeProvider())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        assert (
            await client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"})
        ).status_code == 404


@pytest.mark.parametrize(
    ("url", "token"),
    [
        ("http://backend.example/integrations/elevenlabs/delegate", TOKEN),
        (URL + "?key=bad", TOKEN),
        ("https://backend.example/arbitrary", TOKEN),
        (URL, "short"),
    ],
)
def test_enabled_provider_requires_bounded_service_auth(url: str, token: str) -> None:
    with pytest.raises(ValueError, match="webhook token"):
        Settings(
            elevenlabs_enabled=True,
            elevenlabs_api_key=SecretStr("fixture"),
            elevenlabs_agent_id="agent_fixture",
            elevenlabs_webhook_url=url,
            elevenlabs_webhook_token=SecretStr(token),
        )


async def test_actual_http_disconnect_preserves_work_and_cached_response(fixture: Fixture) -> None:
    f = fixture
    f.worker.gate.clear()
    consumed = False
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal consumed
        if not consumed:
            consumed = True
            return {
                "type": "http.request",
                "body": json.dumps({"goal": "calculate 2+2"}).encode(),
                "more_body": False,
            }
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    await f.app(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": PATH,
            "raw_path": PATH.encode(),
            "root_path": "",
            "query_string": b"",
            "server": ("localhost", 80),
            "client": ("127.0.0.1", 1234),
            "headers": [
                (b"content-type", b"application/json"),
                *[(k.lower().encode(), v.encode()) for k, v in HEADERS.items()],
            ],
        },
        receive,
        send,
    )
    assert sent[0]["status"] == 499
    await eventually(lambda: f.worker.calls == 1)
    assert next(iter(f.session.portfolio.jobs.values())).status == "running"
    f.worker.gate.set()
    f.quiet()
    replay = await asyncio.wait_for(
        f.client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"}), 2
    )
    assert "4" in replay.json()["result"] and f.worker.calls == 1


async def test_expired_conversation_is_rejected_before_janitor_runs(fixture: Fixture) -> None:
    fixture.clock.advance(fixture.manager.settings.session_ttl_seconds + 1)
    result = await fixture.client.post(PATH, headers=HEADERS, json={"goal": "calculate 2+2"})
    assert result.status_code == 404 and fixture.worker.calls == 0


async def test_oversized_service_request_is_rejected_before_work(fixture: Fixture) -> None:
    result = await fixture.client.post(PATH, headers=HEADERS, content=b"x" * 65537)
    assert result.status_code == 413
    assert result.headers["cache-control"] == "no-store"
    assert fixture.worker.calls == 0


async def test_late_connected_event_cannot_reopen_a_closing_session(fixture: Fixture) -> None:
    f = fixture
    f.session.state = "closing"
    f.client.headers.update(
        {
            "Origin": "http://localhost:5173",
            "X-Session-Key": f.session.key,
        }
    )
    response = await f.client.post(
        f"/api/sessions/{f.session.id}/elevenlabs/events",
        json={"kind": "connected", "sequence": 0, "conversation_id": "conv_fixture"},
    )
    assert response.status_code == 409
    assert f.session.state == "closing"
    assert not f.connection.started
    assert f.session.watcher is None
    assert f.session.portfolio.pump is None
