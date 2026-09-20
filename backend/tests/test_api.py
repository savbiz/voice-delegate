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
            client.headers["Origin"] = "http://localhost:5173"
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
            headers={"Origin": "http://localhost:5173"},
        ) as client:
            payload = (await client.post("/api/sessions")).json()
            response = await client.post(
                f"/api/sessions/{payload['id']}/offer",
                headers={"X-Session-Key": payload["key"]},
                json={"sdp": "v=0\r\n"},
            )
            assert response.status_code == 200
    assert provider.connections[0].closed


async def test_deployment_gate_and_cors() -> None:
    from pydantic import SecretStr

    settings = Settings(
        environment="production",
        allowed_origin="https://voice.example",
        access_token=SecretStr("a-test-access-code-long-enough"),
    )
    app = create_app(settings, FakeProvider())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "https://voice.example"},
    ) as client:
        preflight = await client.options(
            "/api/sessions",
            headers={
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,x-session-key,content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["Access-Control-Allow-Origin"] == "https://voice.example"
        assert (await client.post("/api/sessions")).status_code == 401
        client.headers["Authorization"] = "Bearer a-test-access-code-long-enough"
        created = await client.post("/api/sessions")
        assert created.status_code == 201
        payload = created.json()
        client.headers["X-Session-Key"] = payload["key"]
        client.headers.pop("Authorization")
        assert (await client.post(f"/api/sessions/{payload['id']}/close")).status_code == 401
        client.headers["Authorization"] = "Bearer a-test-access-code-long-enough"
        assert (await client.post(f"/api/sessions/{payload['id']}/close")).status_code == 200


async def test_interrupt_requires_ownership_and_reports_status() -> None:
    app = create_app(Settings(), FakeProvider())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://localhost:5173"},
        ) as client:
            created = (await client.post("/api/sessions")).json()
            path = f"/api/sessions/{created['id']}"
            assert (await client.post(path + "/interrupt")).status_code == 404
            client.headers["X-Session-Key"] = created["key"]
            assert (await client.post(path + "/interrupt")).json()["delegation"] == "idle"
            await client.post(path + "/close")
