"""Ownership and transport validation for task controls and numeric audio activity."""

import json

import httpx
import pytest
from conftest import ASGIClientFactory, BlockingWorker, FakeClock
from fastapi import FastAPI
from test_provider import MemorySocket
from voice_delegate.api.routes import build_router
from voice_delegate.config import Settings
from voice_delegate.delegation.contracts import DelegationInput
from voice_delegate.delegation.intent import Job
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import Commentary, WebRTCAnswer
from voice_delegate.providers.realtime import OpenAIRealtimeProvider
from voice_delegate.providers.webrtc import RealtimeWebRTCConnection
from voice_delegate.session.manager import SessionManager


@pytest.mark.parametrize("enabled", [False, True])
async def test_activity_validation_and_targeted_cancel(
    asgi_client: ASGIClientFactory, blocking_worker: BlockingWorker, enabled: bool
) -> None:
    manager = SessionManager(
        FakeProvider(), Settings(intent_cancellation=enabled), worker=blocking_worker
    )
    app = FastAPI()
    app.include_router(build_router(manager))
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    try:
        async with asgi_client(app) as client:
            client.headers.update({"Origin": "http://localhost:5173", "X-Session-Key": session.key})
            path = f"/api/sessions/{session.id}"
            body = {
                "generation": 0,
                "sequence": 0,
                "user_speaking": False,
                "assistant_speaking": False,
            }
            result = await client.post(path + "/activity", json=body)
            assert result.status_code == (200 if enabled else 403)
            if not enabled:
                return
            assert (
                await client.post(path + "/activity", json=body | {"generation": 1})
            ).status_code == 409
            assert (
                await client.post(path + "/activity", json=body | {"user_speaking": "false"})
            ).status_code == 422
            assert (
                await client.post(path + "/activity", json=body | {"text": "no"})
            ).status_code == 422
            session.portfolio.awaiting_playback = True
            await client.post(
                path + "/activity", json=body | {"sequence": 1, "assistant_speaking": True}
            )
            assert not session.portfolio.awaiting_playback
            for identity in ("one", "two"):
                manager.intent.start(
                    session.portfolio, identity, DelegationInput(goal="calculate 1+1"), 0
                )
            result = await client.post(path + "/interrupt", json={"task_id": "one"})
            assert result.json()["delegation"] == "running"
            result = await client.post(path + "/heartbeat")
            assert [task["status"] for task in result.json()["tasks"]] == ["cancelled", "running"]
            await client.post(path + "/interrupt")
            assert not session.portfolio.active
    finally:
        await manager.aclose()


async def test_realtime_detached_delivery_and_terminal_ack_wire_contract() -> None:
    socket = MemorySocket()
    provider = OpenAIRealtimeProvider(
        "fixture", httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    )
    connection = RealtimeWebRTCConnection(WebRTCAnswer("call", "sdp"), socket, provider)
    try:
        await connection.send(Commentary("old-call", "About arithmetic: 4", detached=True))
        item = json.loads(socket.sent[0])["item"]
        assert item["type"] == "message" and "call_id" not in item
        assert "4" in item["content"][0]["text"]
        assert json.loads(socket.sent[1])["type"] == "response.create"
        await connection.send(Commentary("cancelled-call", "Task cancelled", settle_only=True))
        assert len(socket.sent) == 3
        assert json.loads(socket.sent[2])["item"] == {
            "type": "function_call_output",
            "call_id": "cancelled-call",
            "output": "Task cancelled",
        }
        await connection.send(
            Commentary("old-call", "Task cancelled", detached=True, settle_only=True)
        )
        assert len(socket.sent) == 3
    finally:
        await connection.aclose()
        await provider.aclose()


async def test_heartbeat_freezes_terminal_task_duration(
    asgi_client: ASGIClientFactory, fake_clock: FakeClock
) -> None:
    manager = SessionManager(FakeProvider(), Settings(intent_cancellation=True), clock=fake_clock)
    app = FastAPI()
    app.include_router(build_router(manager))
    session = manager.create()
    start = fake_clock()
    session.portfolio.jobs["done"] = Job(
        "done", "Calculate", start, 0, status="completed", finished=start + 3
    )
    session.portfolio.jobs["active"] = Job("active", "Search", start, 0)
    try:
        async with asgi_client(app) as client:
            client.headers.update({"Origin": "http://localhost:5173", "X-Session-Key": session.key})
            for elapsed in (5, 12):
                fake_clock.advance(elapsed - (fake_clock() - start))
                result = await client.post(f"/api/sessions/{session.id}/heartbeat")
                assert result.status_code == 200
                assert [task["elapsed_seconds"] for task in result.json()["tasks"]] == [3, elapsed]
    finally:
        await manager.aclose()
