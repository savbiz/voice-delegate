"""Exact browser origins are shared by routes, CORS and limiter responses."""

from pathlib import Path

import httpx
import pytest
from conftest import ASGIClientFactory
from pydantic import ValidationError
from starlette.responses import Response
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.limits.ratelimit import RateLimitMiddleware
from voice_delegate.providers.fake import FakeProvider

ORIGINS = ["http://localhost:8080", "https://localhost:8080", "https://demo.app.github.dev"]


def test_origin_environment_alias_and_list_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_ALLOWED_ORIGIN", "https://legacy.example")
    assert Settings().allowed_origins == ["https://legacy.example"]
    monkeypatch.setenv("VOICE_ALLOWED_ORIGINS", '["https://one.example","https://two.example"]')
    assert Settings().allowed_origins == ["https://one.example", "https://two.example"]
    assert Settings(allowed_origins=ORIGINS).allowed_origins == ORIGINS


@pytest.mark.parametrize(
    "origins", [[], ["*"], ["https://example.test/"], ["https://a/b"], ["https://u:p@a"]]
)
def test_invalid_origin_lists_are_rejected(origins: list[str]) -> None:
    with pytest.raises(ValidationError):
        Settings(allowed_origins=origins)


def test_production_checks_every_origin() -> None:
    with pytest.raises(ValidationError, match="HTTPS frontend origin"):
        Settings.model_validate(
            {
                "environment": "production",
                "allowed_hosts": ["localhost"],
                "access_token": "a" * 32,
                "allowed_origins": ORIGINS,
            }
        )


async def test_each_origin_can_create_and_close_but_other_origins_cannot(
    asgi_client: ASGIClientFactory, tmp_path: Path
) -> None:
    app = create_app(
        Settings(allowed_origins=ORIGINS, feedback_database=str(tmp_path / "feedback.sqlite3")),
        FakeProvider(),
    )
    async with asgi_client(app) as client:
        for origin in ORIGINS:
            headers = {"Origin": origin}
            preflight = await client.options(
                "/api/sessions", headers={**headers, "Access-Control-Request-Method": "POST"}
            )
            assert preflight.headers["Access-Control-Allow-Origin"] == origin
            response = await client.post("/api/sessions", headers=headers)
            assert response.status_code == 201
            owner = response.json()
            closed = await client.post(
                f"/api/sessions/{owner['id']}/close",
                headers={**headers, "X-Session-Key": owner["key"]},
            )
            assert closed.status_code == 200
        for rejected_origin in (
            None,
            "https://other.example",
            "https://localhost:8080.attacker.test",
        ):
            headers = {} if rejected_origin is None else {"Origin": rejected_origin}
            response = await client.post("/api/sessions", headers=headers)
            assert response.status_code == 403
            assert response.json() == {"detail": "Unexpected request origin"}
            assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize("origin", [*ORIGINS, "https://other.example"])
async def test_limiter_only_reflects_configured_origins(origin: str) -> None:
    limiter = RateLimitMiddleware(Response("ok"), burst=1, clock=lambda: 0, allowed_origins=ORIGINS)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limiter), base_url="http://localhost"
    ) as client:
        assert (await client.get("/")).status_code == 200
        response = await client.get("/", headers={"Origin": origin})
        assert response.status_code == 429
        assert response.headers.get("Access-Control-Allow-Origin") == (
            origin if origin in ORIGINS else None
        )
        assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "origin",
    [
        "https://DEMO.example",
        "https://demo.example:443",
        "http://demo.example:80",
        "https://demo.example:invalid",
        "https://*.example",
    ],
)
def test_noncanonical_origins_are_rejected_before_serving(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(allowed_origins=[origin])
    with pytest.raises(ValidationError):
        Settings(allowed_origin=origin)


@pytest.mark.parametrize(
    "origin",
    [
        "https://demo.example",
        "https://demo.example:8443",
        "http://[::1]:8080",
        "https://xn--bcher-kva.example",
    ],
)
def test_browser_serialized_origins_keep_nondefault_ports_and_idna(origin: str) -> None:
    assert Settings(allowed_origins=[origin]).allowed_origins == [origin]
