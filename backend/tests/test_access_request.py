"""Access requests notify the owner once, stay bounded and never store the request."""

import time
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from conftest import ASGIClientFactory
from pydantic import SecretStr, ValidationError
from voice_delegate.access_request import AccessRequestInput, AccessRequests, Approval, InviteStore
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


# Remote approval: ntfy buttons, Resend email and database-backed invitations.

API = "https://api.example"


def approval_flow(
    tmp_path: Path, seen: list[httpx.Request], email_status: int = 200
) -> AccessRequests:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.resend.com":
            return httpx.Response(email_status, json={"id": "e"})
        return httpx.Response(200)

    return AccessRequests(
        URL,
        httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        store=InviteStore(str(tmp_path / "access.sqlite3")),
        approval=Approval(
            resend_api_key="re_test",
            sender="Invites <invites@example.com>",
            public_api_url=API,
            frontend_url="https://demo.example",
        ),
    )


def buttons(request: httpx.Request) -> tuple[str, str]:
    actions = request.headers["Actions"]
    approve = actions.split("Approve, ")[1].split(",")[0]
    deny = actions.split("Deny, ")[1].split(",")[0]
    return approve.removeprefix(API), deny.removeprefix(API)


async def test_approval_emails_a_code_that_authenticates(
    tmp_path: Path, asgi_client: ASGIClientFactory
) -> None:
    seen: list[httpx.Request] = []
    requests = approval_flow(tmp_path, seen)
    settings = Settings(access_request_url=URL, invite_tokens={"owner": SecretStr("o" * 32)})
    app = create_app(settings, FakeProvider(), requests)
    headers = {"Origin": "http://localhost:5173"}
    async with asgi_client(app) as client:
        config = (await client.post("/api/config", headers=headers)).json()
        assert config["access_request_email"] is True
        bad = await client.post(
            "/api/access-request", json={"contact": "not-an-email"}, headers=headers
        )
        assert bad.status_code == 422
        sent = await client.post(
            "/api/access-request",
            json={"contact": "Visitor@Example.com", "note": "hi"},
            headers=headers,
        )
        assert sent.status_code == 202
        approve, deny = buttons(seen[-1])
        assert "visitor@example.com" in seen[-1].content.decode().lower()
        wrong = await client.post(approve.replace(approve.split("/")[3], "x" * 43))
        assert wrong.status_code == 404
        assert (await client.post(approve)).json() == {"status": "approved"}
        email = seen[-1]
        assert email.url.host == "api.resend.com"
        assert email.headers["Authorization"] == "Bearer re_test"
        body = email.read().decode()
        code = body.split("Invitation code: ")[1].split("\\n")[0]
        assert "visitor@example.com" in body
        assert (await client.post(approve)).status_code == 409
        assert (await client.post(deny)).status_code == 409
        session = await client.post(
            "/api/sessions", json={}, headers={**headers, "Authorization": f"Bearer {code}"}
        )
        assert session.status_code == 201
        refused = await client.post(
            "/api/sessions", json={}, headers={**headers, "Authorization": "Bearer " + "z" * 43}
        )
        assert refused.status_code == 401
    store = InviteStore(str(tmp_path / "access.sqlite3"))
    stored = store.db.execute("SELECT email, note, status FROM requests").fetchall()
    assert stored == [(None, None, "approved")]
    assert store.db.execute("SELECT token_hash FROM invites").fetchone()[0] != code
    store.close()


async def test_denial_repeats_and_failed_email(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    requests = approval_flow(tmp_path, seen, email_status=500)
    await requests.submit(AccessRequestInput(contact="a@example.com"))
    approve, _ = buttons(seen[-1])
    _, request_id, secret, _ = approve.split("/")[1:]
    with pytest.raises(Exception, match="could not be sent"):
        await requests.approve(request_id, secret)
    assert requests.store is not None
    assert requests.store.db.execute("SELECT COUNT(*) FROM invites").fetchone()[0] == 0
    requests.deny(request_id, secret)
    with pytest.raises(Exception, match="already decided"):
        await requests.approve(request_id, secret)
    # A denied address is not notified again during the cooling-off period.
    requests.sent.clear()
    notified = len(seen)
    await requests.submit(AccessRequestInput(contact="A@example.com"))
    assert len(seen) == notified
    await requests.aclose()


def test_pending_requests_expire_and_forget_the_address(tmp_path: Path) -> None:
    now = [0.0]
    store = InviteStore(str(tmp_path / "access.sqlite3"), clock=lambda: now[0])
    opened = store.open("a@example.com", "note")
    assert opened is not None
    now[0] = 7 * 86400 + 1
    with pytest.raises(Exception, match="expired"):
        store.pending(*opened)
    assert store.db.execute("SELECT email, status FROM requests").fetchone() == (None, "expired")
    assert store.open("a@example.com", "") is None
    now[0] = 31 * 86400
    assert store.open("a@example.com", "") is not None
    store.close()


def test_daily_request_budget(tmp_path: Path) -> None:
    store = InviteStore(str(tmp_path / "access.sqlite3"))
    for index in range(20):
        assert store.open(f"user{index}@example.com", "") is not None
    with pytest.raises(Exception, match="Too many"):
        store.open("late@example.com", "")
    store.close()


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"access_email_from": "x@example.com"},
        {"access_email_from": "x@example.com", "public_api_url": "http://api.example"},
        {"access_email_from": "x@example.com", "public_api_url": "https://api.example/path"},
    ],
)
def test_remote_approval_requires_complete_settings(overrides: dict[str, str]) -> None:
    base = {"RESEND_API_KEY": "re_x", "access_request_url": URL}
    with pytest.raises(ValidationError, match="Remote access approval"):
        Settings.model_validate({**base, **overrides})
    complete = {"access_email_from": "x@example.com", "public_api_url": "https://api.example"}
    assert Settings.model_validate({**base, **complete}).resend_api_key.get_secret_value()
