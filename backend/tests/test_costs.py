"""Estimates stay deterministic, isolated, monotonic and honest about missing usage."""

import asyncio
from pathlib import Path

import pytest
from conftest import ASGIClientFactory
from voice_delegate.config import Settings
from voice_delegate.costs import CostLedger, Prices
from voice_delegate.observability.metrics import Metrics
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.session.manager import SessionManager
from voice_delegate_agent.usage import Usage, external_call, model_usage, note, usage_sink


def test_ledger_snapshot_close_and_unknown_rates() -> None:
    now = [0.0]
    ledger = CostLedger(Prices.load(), "live", "gpt-6-luna", lambda: now[0], Metrics())
    assert ledger.snapshot().estimated_usd == 0
    ledger.connect()
    now[0] = 60
    ledger.record(
        Usage(
            worker_calls=1,
            input_tokens=1000,
            cached_tokens=200,
            output_tokens=100,
            web_calls=1,
            decision_calls=1,
            decision_tokens=100,
        )
    )
    summary = ledger.snapshot()
    assert summary.estimated_usd == pytest.approx(
        0.05 + 0.00008 + 0.000002 + 0.00005 + 0.008 + 0.00001
    )
    assert not summary.partial
    ledger.close(True)
    now[0] = 120
    assert ledger.snapshot() == ledger.snapshot()
    assert ledger.snapshot().voice_seconds == 60
    assert ledger.snapshot().final
    ledger.close(False)
    assert not ledger.snapshot().partial
    unknown = CostLedger(Prices.load(), "elevenlabs", "other-model", lambda: now[0], Metrics())
    unknown.connect()
    now[0] += 10
    unknown.record(Usage(input_tokens=1))
    unknown.close(False)
    assert unknown.snapshot().partial
    assert "voice.elevenlabs.second" in unknown.snapshot().unpriced
    assert "worker.other-model.input_token" in unknown.snapshot().unpriced


async def test_usage_sinks_isolate_concurrent_tasks_and_record_failure() -> None:
    left: list[Usage] = []
    right: list[Usage] = []

    async def call(output: list[Usage], fail: bool) -> None:
        with usage_sink(output.append):
            try:
                with external_call("worker_calls"):
                    await asyncio.sleep(0)
                    if fail:
                        raise TimeoutError
                    model_usage(
                        {
                            "input_tokens": 20,
                            "output_tokens": 5,
                            "input_token_details": {"cache_read": 10},
                        }
                    )
            except TimeoutError:
                pass

    await asyncio.gather(call(left, False), call(right, True))
    assert sum(u.input_tokens for u in left) == 20
    assert not any(u.uncertain for u in left)
    assert sum(u.worker_calls for u in right) == 1
    assert any(u.uncertain for u in right)
    note(Usage(web_calls=1))
    assert sum(u.web_calls for u in left + right) == 0
    with usage_sink(left.append):
        model_usage(None)
        model_usage(
            {"input_tokens": 1, "output_tokens": 1, "input_token_details": {"cache_read": -1}}
        )
    assert left[-1].cached_tokens == 0
    assert any(u.uncertain for u in left)


async def test_cost_flag_and_session_freeze(tmp_path: object) -> None:
    now = [0.0]
    disabled = SessionManager(FakeProvider(), Settings(price_file="/missing"), clock=lambda: now[0])
    assert disabled.create().costs is None
    await disabled.aclose()
    manager = SessionManager(FakeProvider(), Settings(cost_estimates=True), clock=lambda: now[0])
    first, second = manager.create(), manager.create()
    await manager.connect(first, "offer")
    assert first.costs is not None and second.costs is not None
    first.costs.record(Usage(web_calls=1))
    now[0] = 60
    await manager.close(first)
    assert first.costs.snapshot().final
    assert first.costs.snapshot().estimated_usd >= 0.058
    assert second.costs.snapshot().estimated_usd == 0
    await manager.aclose()


async def test_remote_usage_reaches_caller_once() -> None:
    import httpx
    from pydantic import SecretStr
    from voice_delegate.scaling.remote import RemoteWorker
    from voice_delegate.scaling.worker_service import create_worker_app
    from voice_delegate_agent.reference import WorkerResult

    class CountedWorker:
        async def delegate_task(self, goal: str, context: str) -> WorkerResult:
            note(Usage(worker_calls=1, input_tokens=300, output_tokens=40, web_calls=1))
            return WorkerResult("done")

    settings = Settings(
        worker_service_token=SecretStr("x" * 32), worker_service_url="http://worker"
    )
    app = create_worker_app(settings, CountedWorker())
    totals: list[Usage] = []
    async with app.router.lifespan_context(app):
        remote = RemoteWorker(settings, httpx.AsyncClient(transport=httpx.ASGITransport(app=app)))
        with usage_sink(totals.append):
            assert (await remote.delegate_task("work", "")).text == "done"
        await remote.aclose()
    assert sum(u.input_tokens for u in totals) == 300
    assert sum(u.web_calls for u in totals) == 1
    assert not any(u.uncertain for u in totals)


async def test_owned_api_returns_live_and_final_cost_snapshot(
    asgi_client: ASGIClientFactory,
) -> None:
    from voice_delegate.api.app import create_app

    app = create_app(Settings(cost_estimates=True), FakeProvider())
    async with asgi_client(app) as client:
        client.headers["Origin"] = "http://localhost:5173"
        created = (await client.post("/api/sessions")).json()
        client.headers["X-Session-Key"] = created["key"]
        path = "/api/sessions/" + created["id"]
        assert (await client.post(path + "/offer", json={"sdp": "v=0\r\n"})).status_code == 200
        current = (await client.post(path + "/heartbeat")).json()["costs"]
        assert current["voice_seconds"] >= 0
        assert current["final"] is False
        closed = (await client.post(path + "/close")).json()["costs"]
        assert closed["final"] is True
        assert closed["estimated_usd"] >= current["estimated_usd"]


def test_invalid_price_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prices.json"
    path.write_text('{"version":"v1","date":"2026-11-02","rates":{"x":{"usd":-1,"source":"test"}}}')
    with pytest.raises(ValueError):
        Prices.load(str(path))


def test_older_remote_response_without_usage_is_partial() -> None:
    from voice_delegate.scaling.worker_service import JobOutput

    assert JobOutput.model_validate({"status": "completed", "text": "done"}).usage.uncertain
