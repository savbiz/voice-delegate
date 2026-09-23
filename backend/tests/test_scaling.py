"""Process-boundary contracts: shared admission, fencing, bounded work and cancellation."""

import asyncio
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.scaling.remote import RemoteWorker
from voice_delegate.scaling.worker_service import create_worker_app
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import SessionError

TOKEN = "test-worker-token-32-characters-long"


def shared(path: Path, instance: str) -> Settings:
    return Settings(
        environment="production",
        public_demo=True,
        instance_id=instance,
        allowed_origin="https://demo.example",
        quota_database=str(path / "quota.db"),
        invite_tokens={"alice": SecretStr("a" * 32), "bob": SecretStr("b" * 32)},
        max_sessions=2,
    )


async def test_two_instances_share_concurrency_and_ownership(tmp_path: Path) -> None:
    a = SessionManager(FakeProvider(), shared(tmp_path, "a"))
    b = SessionManager(FakeProvider(), shared(tmp_path, "b"))
    session = a.create("alice")
    assert session.id.startswith("a-")
    with pytest.raises(SessionError) as full:
        b.create("alice")
    assert full.value.status == 429
    with pytest.raises(SessionError) as foreign:
        b.get(session.id, session.key)
    assert foreign.value.status == 404
    await a.close(session)
    replacement = b.create("alice")
    assert replacement.id.startswith("b-")
    await b.close(replacement)
    await a.aclose()
    await b.aclose()


async def test_crashed_owner_lease_expires_without_refunding_usage(tmp_path: Path) -> None:
    a = SessionManager(FakeProvider(), shared(tmp_path, "a"))
    original = a.create("alice")
    db = a.admission.database
    assert db is not None
    db.execute("UPDATE leases SET expires=0")
    db.commit()
    b = SessionManager(FakeProvider(), shared(tmp_path, "b"))
    recovered = b.create("alice")
    assert db.execute("SELECT SUM(sessions) FROM reservations").fetchone()[0] == 2
    assert recovered.id != original.id
    await b.aclose()
    await a.aclose()


async def test_worker_backpressure_duplicates_and_cancellation_tombstones() -> None:
    class Slow:
        calls = 0
        gate = asyncio.Event()

        async def delegate_task(self, goal: str, context: str) -> str:
            self.calls += 1
            await self.gate.wait()
            return "done"

    worker = Slow()
    settings = Settings(worker_service_token=SecretStr(TOKEN), worker_service_capacity=2)
    app = create_worker_app(settings, worker)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://worker"
        ) as client:
            body = {"request_id": str(uuid4()), "goal": "work", "deadline": time.time() + 30}
            assert (await client.post("/jobs", json=body)).status_code == 401
            client.headers["Authorization"] = "Bearer " + TOKEN
            assert (await client.post("/jobs", json=body)).status_code == 202
            assert (await client.post("/jobs", json=body)).status_code == 202
            results = await asyncio.gather(
                *(
                    client.post("/jobs", json={**body, "request_id": str(uuid4())})
                    for _ in range(20)
                )
            )
            assert sum(r.status_code == 202 for r in results) == 1
            assert sum(r.status_code == 429 for r in results) == 19
            await asyncio.sleep(0)
            assert worker.calls == 2
            assert (await client.delete("/jobs/" + str(body["request_id"]))).status_code == 200
            assert (await client.post("/jobs", json=body)).json()["status"] == "cancelled"
            unknown = str(uuid4())
            await client.delete("/jobs/" + unknown)
            assert (await client.post("/jobs", json={**body, "request_id": unknown})).json()[
                "status"
            ] == "cancelled"
            worker.gate.set()


async def test_remote_worker_executes_graph_and_carries_sources() -> None:
    from voice_delegate_agent.reference import GroundedAnswer

    settings = Settings(
        worker_service_token=SecretStr(TOKEN),
        worker_execution="remote",
        worker_service_url="http://worker",
    )
    app = create_worker_app(settings)
    async with app.router.lifespan_context(app):
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
        remote = RemoteWorker(settings, client)
        result = await remote.delegate_task("docs fallback history", "")
        assert isinstance(result, GroundedAnswer) and result.sources
        await remote.aclose()


async def test_remote_cancellation_cancels_server_job() -> None:
    class Slow:
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def delegate_task(self, goal: str, context: str) -> str:
            self.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()
            return "unreachable"

    worker = Slow()
    settings = Settings(worker_service_token=SecretStr(TOKEN), worker_service_url="http://worker")
    app = create_worker_app(settings, worker)
    async with app.router.lifespan_context(app):
        remote = RemoteWorker(settings, httpx.AsyncClient(transport=httpx.ASGITransport(app=app)))
        task = asyncio.create_task(remote.delegate_task("wait", ""))
        await worker.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(worker.cancelled.wait(), 1)
        await remote.aclose()


async def test_remote_overload_is_reported_as_busy_without_retries() -> None:
    from voice_delegate.delegation.contracts import DelegationInput
    from voice_delegate.delegation.runner import DelegationRunner, DelegationState
    from voice_delegate.providers.fake import FakeConnection

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(429, json={"detail": "Worker capacity reached"})
        return httpx.Response(200, json={"status": "cancelled"})

    settings = Settings(worker_service_token=SecretStr(TOKEN), worker_service_url="http://worker")
    remote = RemoteWorker(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    runner = DelegationRunner(remote)
    state = DelegationState()
    connection = FakeConnection()
    runner.start(state, "overload", DelegationInput(goal="2+2"), connection, lambda: True)
    assert state.task is not None
    await state.task
    assert state.status == "busy"
    assert "not started" in connection.commands[0].content
    assert calls == ["POST", "DELETE"]
    await runner.aclose()
    await remote.aclose()


async def test_remote_worker_polls_at_200ms(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []
    polls = 0
    methods: list[str] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        methods.append(request.method)
        if request.method == "GET":
            polls += 1
            return httpx.Response(
                200, json={"status": "completed" if polls == 3 else "running", "text": "done"}
            )
        return httpx.Response(200, json={"status": "running"})

    monkeypatch.setattr("voice_delegate.scaling.remote.asyncio.sleep", sleep)
    remote = RemoteWorker(
        Settings(worker_service_url="http://worker"),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await remote.delegate_task("test", "") == "done"
    assert delays == [0.2, 0.2]
    assert methods == ["POST", "GET", "GET", "GET", "DELETE"]
    await remote.aclose()


async def test_worker_janitor_recovers_after_sweep_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from voice_delegate.scaling.worker_service import Jobs

    attempts = 0
    recovered = asyncio.Event()

    def sweep(self: Jobs) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary sweep failure")
        recovered.set()

    monkeypatch.setattr(Jobs, "sweep", sweep)
    app = create_worker_app(Settings(worker_service_token=SecretStr(TOKEN)))
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(recovered.wait(), 3)
    assert attempts >= 2
    assert "Worker janitor failed; retrying" in caplog.text
