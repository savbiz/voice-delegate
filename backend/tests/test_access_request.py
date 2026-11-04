"""Access requests notify the owner once, stay bounded and never store the request."""

import time
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from conftest import ASGIClientFactory, PublicSettingsFactory
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


# Remote approval: ntfy buttons, a code notification with a prefilled email, and stored invites.

API = "https://api.example"


def approval_flow(
    tmp_path: Path, seen: list[httpx.Request], code_status: int = 200
) -> AccessRequests:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "Cache" in request.headers:
            return httpx.Response(code_status)
        return httpx.Response(200)

    return AccessRequests(
        URL,
        httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        store=InviteStore(str(tmp_path / "access.sqlite3")),
        approval=Approval(
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
        notice = seen[-1]
        assert str(notice.url) == URL
        assert notice.headers["Cache"] == "no"
        code = notice.content.decode().split("\n")[1]
        gmail, mail = notice.headers["Actions"].split("; ")
        assert gmail.startswith(
            "view, Gmail, https://mail.google.com/mail/?view=cm&fs=1&to=visitor@example.com&su="
        )
        assert mail.startswith("view, Mail app, mailto:visitor@example.com?subject=")
        for action, url_start in ((gmail, "https://"), (mail, "mailto:")):
            # Commas and semicolons separate ntfy actions, so the URLs must not contain them.
            url = action.split(url_start, 1)[1].removesuffix(", clear=true")
            assert "," not in url
            assert ";" not in url
            assert f"Invitation%20code%3A%20{code}" in url
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


async def test_ntfy_web_app_can_read_only_decision_results(
    tmp_path: Path, asgi_client: ASGIClientFactory
) -> None:
    seen: list[httpx.Request] = []
    requests = approval_flow(tmp_path, seen)
    settings = Settings(access_request_url=URL, invite_tokens={"owner": SecretStr("o" * 32)})
    app = create_app(settings, FakeProvider(), requests)
    ntfy = {"Origin": "https://ntfy.example"}
    async with asgi_client(app) as client:
        await client.post(
            "/api/access-request",
            json={"contact": "a@example.com"},
            headers={"Origin": "http://localhost:5173"},
        )
        approve, deny = buttons(seen[-1])
        # A simple POST from the notification origin: the result must be readable so ntfy
        # clears the buttons, and a repeated tap must show the real conflict, not a fetch error.
        for path, status in ((approve, 200), (approve, 409), (deny, 409)):
            response = await client.post(path, headers=ntfy)
            assert response.status_code == status
            assert response.headers["Access-Control-Allow-Origin"] == "https://ntfy.example"
        other = await client.post(approve, headers={"Origin": "https://evil.example"})
        assert "Access-Control-Allow-Origin" not in other.headers
        config = await client.post("/api/config", headers=ntfy)
        assert "Access-Control-Allow-Origin" not in config.headers


async def test_denial_repeats_and_failed_email(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    requests = approval_flow(tmp_path, seen, code_status=500)
    await requests.submit(AccessRequestInput(contact="a@example.com"))
    approve, _ = buttons(seen[-1])
    _, request_id, secret, _ = approve.split("/")[1:]
    with pytest.raises(Exception, match="could not be delivered"):
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
        {"public_api_url": "http://api.example"},
        {"public_api_url": "https://api.example/path"},
        {"public_api_url": "https://api.example", "access_request_url": ""},
    ],
)
def test_remote_approval_requires_complete_settings(overrides: dict[str, str]) -> None:
    base = {"access_request_url": URL}
    with pytest.raises(ValidationError, match="Remote access approval"):
        Settings.model_validate({**base, **overrides})
    settings = Settings.model_validate({**base, "public_api_url": "https://api.example"})
    assert settings.public_api_url == "https://api.example"


def test_invite_cli_adds_lists_and_revokes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from voice_delegate.invites import main

    path = tmp_path / "access.sqlite3"
    monkeypatch.setenv("VOICE_ACCESS_DATABASE", str(path))
    assert main(["add", "alice"]) == 0
    token = capsys.readouterr().out.strip()
    assert len(token) >= 40
    assert main(["add", "alice"]) == 1
    assert main(["add", "email-forged"]) == 2
    assert main(["add", "bad name"]) == 2
    capsys.readouterr()
    assert main(["list"]) == 0
    listed = capsys.readouterr().out
    assert listed.startswith("alice\t") and token not in listed
    store = InviteStore(str(path))
    assert store.principal(token) == "alice"
    assert token not in path.read_bytes().decode(errors="ignore")
    store.close()
    assert main(["revoke", "alice"]) == 0
    assert main(["revoke", "alice"]) == 1
    store = InviteStore(str(path))
    assert store.principal(token) is None
    store.close()


async def test_public_demo_with_database_invites_only_rejects_unknown_codes(
    public_settings: PublicSettingsFactory, tmp_path: Path, asgi_client: ASGIClientFactory
) -> None:
    settings = public_settings(tmp_path, invite_tokens={})
    store = InviteStore(settings.access_database)
    store.add("alice", "t" * 43)
    store.close()
    app = create_app(settings, FakeProvider())
    headers = {"Origin": "https://demo.example", "Host": "localhost"}
    async with asgi_client(app) as client:
        config = (await client.post("/api/config", headers=headers)).json()
        assert config["requires_access_code"] is True
        for authorization in ({}, {"Authorization": "Bearer " + "x" * 43}):
            denied = await client.post(
                "/api/sessions", json={}, headers={**headers, **authorization}
            )
            assert denied.status_code == 401
        allowed = await client.post(
            "/api/sessions", json={}, headers={**headers, "Authorization": "Bearer " + "t" * 43}
        )
        assert allowed.status_code == 201
