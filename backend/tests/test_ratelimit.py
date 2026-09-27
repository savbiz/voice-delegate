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


def test_bucket_storage_evicts_least_recently_used_client() -> None:
    limiter = RateLimitMiddleware(ok, burst=1, max_clients=2, clock=lambda: 0)
    assert limiter.allow("first")
    assert limiter.allow("second")
    assert not limiter.allow("first")
    assert limiter.allow("third")
    assert list(limiter.buckets) == ["first", "third"]
    assert not limiter.allow("first")
    assert not limiter.allow("third")
    assert limiter.allow("second")
    assert list(limiter.buckets) == ["third", "second"]


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


@pytest.mark.parametrize("header", ["192.0.2.1, bad", "192.0.2.1,", "", "192.0.2.1:80"])
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


@pytest.mark.parametrize("host", ["localhost", "wrong.example"])
async def test_preflights_share_the_request_budget_and_validate_host(
    host: str, asgi_client: ASGIClientFactory
) -> None:
    app = create_app(Settings(allowed_hosts=["localhost"]), FakeProvider())
    for middleware in app.user_middleware:
        if cast(object, middleware.cls) is RateLimitMiddleware:
            middleware.kwargs.update(clock=lambda: 0, burst=2)
    headers = {
        "Host": host,
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Authorization, Content-Type",
    }
    async with asgi_client(app) as client:
        for _ in range(2):
            response = await client.options("/api/sessions", headers=headers)
            assert response.status_code == (200 if host == "localhost" else 400)
        blocked = await client.options("/api/sessions", headers=headers)
        assert blocked.status_code == 429
        assert blocked.headers["Cache-Control"] == "no-store"
        # OPTIONS cannot use a separate budget from actual application requests.
        assert (
            await client.post("/api/config", headers={"Origin": headers["Origin"]})
        ).status_code == 429


@pytest.mark.parametrize("origin", ["http://localhost:5173", "https://untrusted.example", ""])
async def test_rate_limit_rejection_is_readable_only_by_allowed_frontend(
    origin: str, asgi_client: ASGIClientFactory
) -> None:
    app = create_app(Settings(), FakeProvider())
    for middleware in app.user_middleware:
        if cast(object, middleware.cls) is RateLimitMiddleware:
            middleware.kwargs.update(clock=lambda: 0, burst=1)
    async with asgi_client(app) as client:
        assert (await client.get("/healthz")).status_code == 200
        response = await client.post("/api/config", headers={"Origin": origin} if origin else {})
        assert response.status_code == 429
        assert response.headers["Cache-Control"] == "no-store"
        if origin == "http://localhost:5173":
            assert response.headers["Access-Control-Allow-Origin"] == origin
            assert response.headers["Vary"] == "Origin"
        else:
            assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize("hops", [1, 2])
@pytest.mark.parametrize("prefix", [b"invalid", b"\xff", b"", b"bad," * 1000])
async def test_untrusted_forwarded_prefix_cannot_change_client_bucket(
    hops: int, prefix: bytes
) -> None:
    limiter = RateLimitMiddleware(
        ok, trust_proxy=True, trusted_proxy_hops=hops, burst=1, clock=lambda: 0
    )
    suffix = b"192.0.2.10" + (b", invalid-trusted-hop" if hops == 2 else b"")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limiter), base_url="http://testserver"
    ) as client:
        assert (await client.get("/", headers={b"X-Forwarded-For": suffix})).status_code == 200
        assert (
            await client.get("/", headers={b"X-Forwarded-For": prefix + b", " + suffix})
        ).status_code == 429
    assert list(limiter.buckets) == ["192.0.2.10"]


@pytest.mark.parametrize("forwarded", [False, True])
async def test_ipv6_hosts_share_a_subnet_bucket(forwarded: bool) -> None:
    limiter = RateLimitMiddleware(ok, trust_proxy=forwarded, burst=1, clock=lambda: 0)
    addresses = ["2001:db8:1::1", "2001:0db8:0001:0000::abcd", "2001:db8:2::1"]
    statuses = []
    for address in addresses:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=limiter, client=("192.0.2.1" if forwarded else address, 1)
            ),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                "/", headers={"X-Forwarded-For": address} if forwarded else {}
            )
            statuses.append(response.status_code)
    assert statuses == [200, 429, 200]
    assert set(limiter.buckets) == {"2001:db8:1::/64", "2001:db8:2::/64"}


def test_short_forwarded_chain_uses_socket_subnet() -> None:
    limiter = RateLimitMiddleware(ok, trust_proxy=True, trusted_proxy_hops=2)
    assert (
        limiter.client(
            {
                "client": ("2001:db8::123", 1),
                "headers": [(b"x-forwarded-for", b"192.0.2.1")],
            }
        )
        == "2001:db8::/64"
    )
