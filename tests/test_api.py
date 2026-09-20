"""Exercise the HTTP boundary in-process with real sockets disabled."""

import httpx

from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider


async def test_offer_auth_validation_and_cleanup() -> None:
    provider = FakeProvider()
    app = create_app(Settings(), provider)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            assert (await client.post("/api/sessions")).status_code == 403
            client.headers["Origin"] = "http://localhost:8000"
            created = await client.post("/api/sessions")
            assert created.status_code == 201
            assert created.headers["Cache-Control"] == "no-store"
            payload = created.json()
            path = f"/api/sessions/{payload['id']}"
            assert (await client.post(path + "/close")).status_code == 404
            client.headers["X-Session-Key"] = payload["key"]
            assert (await client.post(path + "/token")).status_code == 501
            assert (await client.post(path + "/offer", json={"sdp": "  "})).status_code == 422
            malicious = {"sdp": "v=0\r\n", "model": "untrusted"}
            assert (await client.post(path + "/offer", json=malicious)).status_code == 422
            answer = await client.post(path + "/offer", json={"sdp": "v=0\r\n"})
            assert answer.status_code == 200
            assert "session_id" not in answer.json()
            duplicate = await client.post(path + "/offer", json={"sdp": "v=0\r\n"})
            assert duplicate.status_code == 409
            assert (await client.post(path + "/heartbeat")).json()["state"] == "connected"
            closed = await client.post(path + "/close")
            assert closed.json()["finalized"] is True
    assert provider.connections[0].closed


async def test_body_limit_and_host_check() -> None:
    app = create_app(Settings(max_body_bytes=1024), FakeProvider())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/sessions", content=b"x" * 1025)
        assert response.status_code == 413
        response = await client.get("/healthz", headers={"Host": "untrusted.example"})
        assert response.status_code == 400


async def test_lifespan_closes_active_session() -> None:
    provider = FakeProvider()
    app = create_app(Settings(), provider)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://localhost:8000"},
        ) as client:
            payload = (await client.post("/api/sessions")).json()
            response = await client.post(
                f"/api/sessions/{payload['id']}/offer",
                headers={"X-Session-Key": payload["key"]},
                json={"sdp": "v=0\r\n"},
            )
            assert response.status_code == 200
    assert provider.connections[0].closed
