"""Feedback isolation, content exclusion, retry safety and bounded retention."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from conftest import ASGIClientFactory
from pydantic import SecretStr
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.feedback import FeedbackInput, FeedbackStore
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.session.models import SessionError


def report() -> FeedbackInput:
    return FeedbackInput(diagnostic_id=uuid4(), category="audio", state="ended")


def test_feedback_retry_isolation_limits_and_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = str(tmp_path / "feedback.sqlite3")
    store = FeedbackStore(path, capacity=6)
    body = report()
    first = store.submit("alice", body, "openai")
    assert store.submit("alice", body, "openai") == first
    with pytest.raises(SessionError) as exc:
        store.submit("bob", body, "openai")
    assert exc.value.status == 404
    with pytest.raises(SessionError) as exc:
        store.submit("alice", body.model_copy(update={"category": "other"}), "openai")
    assert exc.value.status == 409
    for _ in range(4):
        store.submit("alice", report(), "openai")
    with pytest.raises(SessionError) as exc:
        store.submit("alice", report(), "openai")
    assert exc.value.status == 429
    store.submit("bob", report(), "openai")
    with pytest.raises(SessionError) as exc:
        store.submit("carol", report(), "openai")
    assert exc.value.status == 503
    store.close()
    store = FeedbackStore(path, capacity=6)
    assert store.db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 6
    import time

    now = time.time()
    monkeypatch.setattr("voice_delegate.feedback.time.time", lambda: now + 7 * 86400 + 1)
    store.purge()
    assert store.db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
    store.submit("alice", report(), "openai")
    store.close()


async def test_feedback_api_auth_schema_and_private_storage(
    asgi_client: ASGIClientFactory, tmp_path: Path
) -> None:
    path = str(tmp_path / "feedback.sqlite3")
    secret = "private-invitation-never-stored-123456"
    settings = Settings(feedback_database=path, invite_tokens={"alice": SecretStr(secret)})
    app = create_app(settings, FakeProvider())
    async with asgi_client(app) as client:
        body = report().model_dump(mode="json")
        assert (await client.post("/api/feedback", json=body)).status_code == 403
        client.headers["Origin"] = settings.allowed_origins[0]
        assert (await client.post("/api/feedback", json=body)).status_code == 401
        client.headers["Authorization"] = "Bearer " + secret
        for field in ("transcript", "audio", "message", "provider", "session_key"):
            assert (
                await client.post("/api/feedback", json={**body, field: "private"})
            ).status_code == 422
        result = await client.post("/api/feedback", json=body)
        assert result.status_code == 201
        assert result.headers["Cache-Control"] == "no-store"
        assert result.json() == {"diagnostic_id": body["diagnostic_id"]}
        assert (await client.post("/api/feedback", json=body)).json() == result.json()
        assert (await client.get("/api/feedback")).status_code == 405
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute("SELECT * FROM feedback").fetchall()
        assert len(rows) == 1
        assert all(text not in str(rows) for text in (secret, "alice", "private"))


async def test_feedback_disabled_without_auth() -> None:
    app = create_app(Settings(), FakeProvider())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://localhost:5173"},
    ) as client:
        assert (
            await client.post("/api/feedback", json=report().model_dump(mode="json"))
        ).status_code == 503


async def test_feedback_and_app_use_distribution_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def distribution_version(name: str) -> str:
        assert name == "voice-delegate"
        return "9.8.7"

    monkeypatch.setattr("voice_delegate.api.app.version", distribution_version)
    monkeypatch.setattr("voice_delegate.feedback.version", distribution_version)
    app = create_app(Settings(), FakeProvider())
    async with app.router.lifespan_context(app):
        store = FeedbackStore(str(tmp_path / "feedback.sqlite3"))
        try:
            store.submit("alice", report(), "openai")
            assert store.db.execute("SELECT version FROM feedback").fetchone() == (app.version,)
            assert app.version == "9.8.7"
        finally:
            store.close()


async def test_feedback_records_the_selected_adapter_when_configured(
    asgi_client: ASGIClientFactory, tmp_path: Path
) -> None:
    path = str(tmp_path / "feedback.sqlite3")
    secret = "private-invitation-never-stored-123456"
    settings = Settings(
        feedback_database=path,
        invite_tokens={"alice": SecretStr(secret)},
        session_ui=True,
        openai_api_key=SecretStr("fixture"),
        azure_api_key=SecretStr("fixture"),
        azure_endpoint="https://fixture.openai.azure.com",
    )
    app = create_app(settings, FakeProvider())
    async with asgi_client(app) as client:
        client.headers["Origin"] = settings.allowed_origins[0]
        client.headers["Authorization"] = "Bearer " + secret
        chosen = {**report().model_dump(mode="json"), "adapter": "azure"}
        unknown = {**report().model_dump(mode="json"), "adapter": "elevenlabs"}
        assert (await client.post("/api/feedback", json=chosen)).status_code == 201
        assert (await client.post("/api/feedback", json=unknown)).status_code == 201
    with closing(sqlite3.connect(path)) as database:
        rows = dict(database.execute("SELECT id, provider FROM feedback"))
    assert rows[chosen["diagnostic_id"]] == "azure"
    assert rows[unknown["diagnostic_id"]] == "openai"


def test_feedback_note_is_optional_plain_and_never_a_key(tmp_path: Path) -> None:
    assert report().note == ""
    note = FeedbackInput(
        diagnostic_id=uuid4(), category="wrong_answer", state="ended", note="  It said\nJuve won  "
    )
    assert note.note == "It said Juve won"
    for pasted in ("sk-" + "a" * 40, "my code is " + "Q" * 43):
        with pytest.raises(ValueError, match="key or code"):
            FeedbackInput(diagnostic_id=uuid4(), category="other", state="ended", note=pasted)
    with pytest.raises(ValueError, match="at most 500"):
        FeedbackInput(diagnostic_id=uuid4(), category="other", state="ended", note="x " * 251)
    store = FeedbackStore(str(tmp_path / "feedback.sqlite3"))
    store.submit("alice", note, "openai")
    # A retry with the same diagnostic ID must carry the same note.
    with pytest.raises(SessionError) as exc:
        store.submit("alice", note.model_copy(update={"note": "different"}), "openai")
    assert exc.value.status == 409
    stored = store.db.execute("SELECT note FROM feedback").fetchall()
    assert stored == [("It said Juve won",)]
    store.submit("alice", report(), "openai")
    assert store.db.execute("SELECT COUNT(*) FROM feedback WHERE note IS NULL").fetchone() == (1,)
    store.close()


def test_feedback_store_adds_the_note_column_to_an_existing_database(tmp_path: Path) -> None:
    path = tmp_path / "feedback.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "CREATE TABLE feedback (id TEXT PRIMARY KEY, principal TEXT, category TEXT, "
            "state TEXT, provider TEXT, version TEXT, created REAL)"
        )
        db.execute("INSERT INTO feedback VALUES ('old', 'p', 'audio', 'ended', 'openai', '0', 9e9)")
        db.commit()
    store = FeedbackStore(str(path))
    store.submit("alice", report().model_copy(update={"note": "Audio cut out"}), "openai")
    rows = store.db.execute("SELECT id, note FROM feedback ORDER BY id").fetchall()
    assert ("old", None) in rows
    assert any(note == "Audio cut out" for _, note in rows)
    store.close()


async def test_feedback_api_accepts_a_note(asgi_client: ASGIClientFactory, tmp_path: Path) -> None:
    path = str(tmp_path / "feedback.sqlite3")
    secret = "private-invitation-never-stored-123456"
    settings = Settings(feedback_database=path, invite_tokens={"alice": SecretStr(secret)})
    app = create_app(settings, FakeProvider())
    async with asgi_client(app) as client:
        client.headers["Origin"] = settings.allowed_origins[0]
        client.headers["Authorization"] = "Bearer " + secret
        body = {**report().model_dump(mode="json"), "note": "Wrong score"}
        assert (await client.post("/api/feedback", json=body)).status_code == 201
        keyed = {**report().model_dump(mode="json"), "note": "sk-" + "b" * 40}
        assert (await client.post("/api/feedback", json=keyed)).status_code == 422
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT note FROM feedback").fetchall() == [("Wrong score",)]


async def test_new_reports_notify_the_owner_without_the_note(
    asgi_client: ASGIClientFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from voice_delegate import feedback as feedback_module
    from voice_delegate.api import app as app_module

    sent: list[httpx.Request] = []
    status = [200]

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(status[0])

    def notifier(url: str) -> feedback_module.FeedbackNotifier:
        return feedback_module.FeedbackNotifier(
            url, httpx.AsyncClient(transport=httpx.MockTransport(handle))
        )

    monkeypatch.setattr(app_module, "FeedbackNotifier", notifier)
    secret = "private-invitation-never-stored-123456"
    settings = Settings(
        feedback_database=str(tmp_path / "feedback.sqlite3"),
        invite_tokens={"alice": SecretStr(secret)},
        access_request_url="https://ntfy.example/private-topic-123",
    )
    app = create_app(settings, FakeProvider())
    async with asgi_client(app) as client:
        client.headers["Origin"] = settings.allowed_origins[0]
        client.headers["Authorization"] = "Bearer " + secret
        body = {
            **report().model_dump(mode="json"),
            "category": "wrong_answer",
            "note": "It said Juve won",
        }
        assert (await client.post("/api/feedback", json=body)).status_code == 201
        assert (await client.post("/api/feedback", json=body)).status_code == 201
        assert len(sent) == 1, "a retry of the same report must not notify again"
        notice = sent[0]
        assert str(notice.url) == settings.access_request_url
        assert notice.headers["Title"] == "New feedback to read"
        text = notice.content.decode()
        assert text.startswith("Wrong answer · openai · ended")
        assert "A note is attached" in text
        assert "Juve" not in text and secret not in text and "alice" not in text
        status[0] = 500
        silent = report().model_dump(mode="json")
        assert (await client.post("/api/feedback", json=silent)).status_code == 201
        assert len(sent) == 2
        assert "note" not in sent[1].content.decode()
