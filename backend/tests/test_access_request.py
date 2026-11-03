"""Access requests notify the owner once, stay bounded and never store the request."""

import time
from collections.abc import Callable

import httpx
import pytest
from conftest import ASGIClientFactory
from pydantic import ValidationError
from voice_delegate.access_request import AccessRequestInput, AccessRequests
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider

URL = "https://ntfy.example/private-topic-123"


def notifier(
    seen: list[httpx.Request],
    status: int = 200,
    limit: int = 5,
    window: float = 3600,
    clock: Callable[[], float] = time.monotonic,
) -> AccessRequests:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return AccessRequests(URL, client, limit, window, clock)


async def test_request_is_forwarded_deduplicated_and_budgeted() -> None:
    seen: list[httpx.Request] = []
    now = [0.0]
    requests = notifier(seen, limit=2, window=100, clock=lambda: now[0])
    await requests.submit(AccessRequestInput(contact="a@example.com", note="hi"))
    await requests.submit(AccessRequestInput(contact=" A@example.com ", note="again"))
    assert len(seen) == 1
    assert seen[0].content == b"Contact: a@example.com\nNote: hi"
    assert str(seen[0].url) == URL
    await requests.submit(AccessRequestInput(contact="b@example.com"))
    with pytest.raises(Exception, match="Too many"):
        await requests.submit(AccessRequestInput(contact="c@example.com"))
    now[0] = 101
    await requests.submit(AccessRequestInput(contact="c@example.com"))
    assert len(seen) == 3
    await requests.aclose()


async def test_failed_delivery_is_reported_and_not_counted() -> None:
    seen: list[httpx.Request] = []
    requests = notifier(seen, status=500, limit=1)
    for _ in range(2):
        with pytest.raises(Exception, match="temporarily unavailable"):
            await requests.submit(AccessRequestInput(contact="a@example.com"))
    assert len(seen) == 2
    await requests.aclose()


def test_input_is_bounded() -> None:
    with pytest.raises(ValidationError):
        AccessRequestInput(contact="x")
    with pytest.raises(ValidationError):
        AccessRequestInput(contact="a@example.com", note="n" * 301)
    with pytest.raises(ValidationError):
        AccessRequestInput.model_validate({"contact": "a@example.com", "extra": 1})


@pytest.mark.parametrize(
    "url",
    [
        "http://ntfy.example/private-topic-123",
        "https://ntfy.example/short",
        "https://u:p@n.example/abcdefghij",
        "https://n.example/abcdefghij?x=1",
    ],
)
def test_url_must_be_an_https_topic(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(access_request_url=url)


async def test_api_endpoint_and_capability_flag(asgi_client: ASGIClientFactory) -> None:
    headers = {"Origin": "http://localhost:5173"}
    app = create_app(Settings(), FakeProvider())
    async with asgi_client(app) as client:
        config = await client.post("/api/config", headers=headers)
        assert config.json()["access_request_available"] is False
        response = await client.post(
            "/api/access-request", json={"contact": "a@example.com"}, headers=headers
        )
        assert response.status_code == 503
    seen: list[httpx.Request] = []
    app = create_app(Settings(), FakeProvider(), notifier(seen))
    async with asgi_client(app) as client:
        config = await client.post("/api/config", headers=headers)
        assert config.json()["access_request_available"] is True
        response = await client.post(
            "/api/access-request", json={"contact": "a@example.com"}, headers=headers
        )
        assert response.status_code == 202
        assert len(seen) == 1
        bad_origin = await client.post(
            "/api/access-request",
            json={"contact": "a@example.com"},
            headers={"Origin": "https://x.example"},
        )
        assert bad_origin.status_code == 403
        invalid = await client.post("/api/access-request", json={"contact": "a"}, headers=headers)
        assert invalid.status_code == 422
