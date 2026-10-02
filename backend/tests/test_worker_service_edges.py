"""Worker service error contracts, ledger expiry and bounded execution."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from conftest import ASGIClientFactory, BlockingWorker, FakeClock
from pydantic import SecretStr
from voice_delegate.config import Settings
from voice_delegate.scaling.worker_service import Job, JobInput, Jobs, create_worker_app


async def test_job_http_errors_results_and_tombstone_expiry(
    asgi_client: ASGIClientFactory,
    blocking_worker: BlockingWorker,
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "voice_delegate.scaling.worker_service.time", SimpleNamespace(time=fake_clock)
    )
    settings = Settings(worker_service_token=SecretStr("x" * 32), worker_max_records=32)
    jobs = Jobs(blocking_worker, settings)
    monkeypatch.setattr("voice_delegate.scaling.worker_service.Jobs", lambda *args: jobs)
    app = create_worker_app(settings, blocking_worker)
    key = uuid4()
    body = {"request_id": str(key), "goal": "wait", "deadline": fake_clock() + 30}
    async with asgi_client(app) as client:
        client.headers["Authorization"] = "Bearer " + "x" * 32
        assert (await client.get(f"/jobs/{key}")).status_code == 404
        for deadline in (fake_clock(), fake_clock() + 121):
            assert (
                await client.post("/jobs", json={**body, "deadline": deadline})
            ).status_code == 422
        assert (await client.post("/jobs", json=body)).status_code == 202
        await blocking_worker.started.wait()
        assert (await client.get(f"/jobs/{key}")).json()["status"] == "running"
        assert (await client.post("/jobs", json={**body, "goal": "different"})).status_code == 409
        blocking_worker.gate.set()
        task = jobs.items[key].task
        assert task is not None
        await task
        result = await client.get(f"/jobs/{key}")
        assert result.status_code == 200 and result.json()["text"] == "done"
        for _ in range(31):
            assert (await client.delete(f"/jobs/{uuid4()}")).status_code == 200
        assert (await client.delete(f"/jobs/{uuid4()}")).status_code == 503
        fake_clock.advance(181)
        assert (await client.get(f"/jobs/{key}")).status_code == 404
        assert not jobs.items
        assert (await client.delete(f"/jobs/{uuid4()}")).status_code == 200


async def test_job_run_times_out_cooperative_worker(blocking_worker: BlockingWorker) -> None:
    blocking_worker.return_on_cancel = False
    jobs = Jobs(blocking_worker, Settings(delegation_timeout_seconds=0.01))
    job = Job("fingerprint", 0)
    body = JobInput(request_id=uuid4(), goal="wait", deadline=0)
    await jobs.run(job, body)
    assert job.status == "timeout"
    assert blocking_worker.cancelled.is_set()
    assert not job.text and not job.source_ids


async def test_expired_running_job_is_cancelled_before_removal(
    blocking_worker: BlockingWorker, fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "voice_delegate.scaling.worker_service.time", SimpleNamespace(time=fake_clock)
    )
    blocking_worker.return_on_cancel = False
    jobs = Jobs(blocking_worker, Settings())
    body = JobInput(request_id=uuid4(), goal="wait", deadline=fake_clock() + 30)
    job = jobs.start(body)
    await blocking_worker.started.wait()
    fake_clock.advance(181)
    jobs.sweep()
    assert job.task is not None
    with pytest.raises(asyncio.CancelledError):
        await job.task
    jobs.sweep()
    assert not jobs.items
