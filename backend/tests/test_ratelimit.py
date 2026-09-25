"""Rate limits reject traffic before body buffering and distrust spoofed headers."""

from typing import cast

import httpx
import pytest
from conftest import ASGIClientFactory
from starlette.responses import Response
from starlette.types import Receive, Scope, Send
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.limits.ratelimit import RateLimitMiddleware
from voice_delegate.providers.fake import FakeProvider


async def ok(scope: Scope, receive: Receive, send: Send) -> None:
    await Response("ok")(scope, receive, send)


async def test_burst_limit_refill_and_client_isolation() -> None:
    now = [0.0]
    limiter = RateLimitMiddleware(ok, clock=lambda: now[0])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limiter, client=("192.0.2.1", 1)),
        base_url="http://testserver",
    ) as client:
        for _ in range(100):
            assert (await client.get("/")).status_code == 200
        blocked = await client.get("/")
        assert blocked.status_code == 429
        assert blocked.headers["Cache-Control"] == "no-store"
        now[0] = 0.05
        assert (await client.get("/")).status_code == 200
        assert (await client.get("/")).status_code == 429
        now[0] = 10
        for _ in range(100):
            assert (await client.get("/")).status_code == 200
        assert (await client.get("/")).status_code == 429
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limiter, client=("192.0.2.2", 1)),
        base_url="http://testserver",
    ) as other:
        assert (await other.get("/")).status_code == 200


@pytest.mark.parametrize("trust", [False, True])
async def test_forwarded_addresses_require_explicit_trust(trust: bool) -> None:
    limiter = RateLimitMiddleware(ok, burst=1, trust_proxy=trust, clock=lambda: 0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limiter), base_url="http://testserver"
    ) as client:
        assert (await client.get("/", headers={"X-Forwarded-For": "192.0.2.1"})).status_code == 200
        response = await client.get("/", headers={"X-Forwarded-For": "10.0.0.1, 192.0.2.2"})
        assert response.status_code == (200 if trust else 429)
        response = await client.get("/", headers={"X-Forwarded-For": "10.0.0.2, 192.0.2.2"})
        assert response.status_code == 429


async def test_invalid_forwarded_header_falls_back_to_peer() -> None:
    limiter = RateLimitMiddleware(ok, burst=1, trust_proxy=True, clock=lambda: 0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limiter), base_url="http://testserver"
    ) as client:
        assert (await client.get("/")).status_code == 200
        assert (await client.get("/", headers={"X-Forwarded-For": "bad"})).status_code == 429


async def test_rate_limit_runs_before_body_limit(
    asgi_client: ASGIClientFactory,
) -> None:
    app = create_app(Settings(max_body_bytes=1024), FakeProvider())
    # Freeze the clock so the test does not depend on execution speed.
    for middleware in app.user_middleware:
        if cast(object, middleware.cls) is RateLimitMiddleware:
            middleware.kwargs["clock"] = lambda: 0
    async with asgi_client(app) as client:
        for _ in range(100):
            assert (await client.get("/healthz")).status_code == 200
        assert (await client.post("/api/sessions", content=b"x" * 1025)).status_code == 429


def test_bucket_storage_is_bounded_without_evicting_active_limits() -> None:
    now = [0.0]
    limiter = RateLimitMiddleware(ok, burst=1, max_clients=1, clock=lambda: now[0])
    assert limiter.allow("first")
    assert not limiter.allow("second")
    assert not limiter.allow("first")
    now[0] = 1
    assert limiter.allow("second")
    assert len(limiter.buckets) == 1


@pytest.mark.parametrize("trust", [False, True])
async def test_app_wires_proxy_trust(trust: bool, asgi_client: ASGIClientFactory) -> None:
    app = create_app(Settings(trust_proxy=trust), FakeProvider())
    for middleware in app.user_middleware:
        if cast(object, middleware.cls) is RateLimitMiddleware:
            middleware.kwargs.update(clock=lambda: 0, burst=1)
    async with asgi_client(app) as client:
        assert (
            await client.get("/healthz", headers={"X-Forwarded-For": "192.0.2.1"})
        ).status_code == 200
        response = await client.get("/healthz", headers={"X-Forwarded-For": "192.0.2.2"})
        assert response.status_code == (200 if trust else 429)


@pytest.mark.parametrize("hops", [1, 2])
async def test_appended_forwarded_spoofing_cannot_reset_bucket(hops: int) -> None:
    limiter = RateLimitMiddleware(
        ok, trust_proxy=True, trusted_proxy_hops=hops, burst=1, clock=lambda: 0
    )
    suffix = ", 192.0.2.10" + (", 10.0.0.2" if hops == 2 else "")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limiter), base_url="http://testserver"
    ) as client:
        assert (
            await client.get("/", headers={"X-Forwarded-For": "198.51.100.1" + suffix})
        ).status_code == 200
        assert (
            await client.get("/", headers={"X-Forwarded-For": "198.51.100.2" + suffix})
        ).status_code == 429


@pytest.mark.parametrize("header", ["bad, 192.0.2.1", "192.0.2.1,", "", "192.0.2.1:80"])
async def test_malformed_chain_uses_socket_bucket(header: str) -> None:
    limiter = RateLimitMiddleware(ok, trust_proxy=True, burst=1, clock=lambda: 0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limiter), base_url="http://testserver"
    ) as client:
        assert (await client.get("/")).status_code == 200
        assert (await client.get("/", headers={"X-Forwarded-For": header})).status_code == 429


async def test_host_mismatch_requests_are_rate_limited(asgi_client: ASGIClientFactory) -> None:
    app = create_app(Settings(allowed_hosts=["localhost"]), FakeProvider())
    for middleware in app.user_middleware:
        if cast(object, middleware.cls) is RateLimitMiddleware:
            middleware.kwargs.update(clock=lambda: 0, burst=1)
    async with asgi_client(app) as client:
        assert (await client.get("/healthz", headers={"Host": "wrong.example"})).status_code == 400
        response = await client.get("/healthz", headers={"Host": "another.example"})
        assert response.status_code == 429
        assert response.headers["Cache-Control"] == "no-store"
