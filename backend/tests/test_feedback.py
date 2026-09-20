"""Feedback isolation, content exclusion, retry safety and bounded retention."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
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
    first = store.submit("alice", body, "live")
    assert store.submit("alice", body, "live") == first
    with pytest.raises(SessionError) as exc:
        store.submit("bob", body, "live")
    assert exc.value.status == 404
    with pytest.raises(SessionError) as exc:
        store.submit("alice", body.model_copy(update={"category": "other"}), "live")
    assert exc.value.status == 409
    for _ in range(4):
        store.submit("alice", report(), "live")
    with pytest.raises(SessionError) as exc:
        store.submit("alice", report(), "live")
    assert exc.value.status == 429
    store.submit("bob", report(), "live")
    with pytest.raises(SessionError) as exc:
        store.submit("carol", report(), "live")
    assert exc.value.status == 503
    store.close()
    store = FeedbackStore(path, capacity=6)
    assert store.db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 6
    import time

    now = time.time()
    monkeypatch.setattr("voice_delegate.feedback.time.time", lambda: now + 7 * 86400 + 1)
    store.purge()
    assert store.db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
    store.submit("alice", report(), "live")
    store.close()


async def test_feedback_api_auth_schema_and_private_storage(tmp_path: Path) -> None:
    path = str(tmp_path / "feedback.sqlite3")
    secret = "private-invitation-never-stored-123456"
    settings = Settings(feedback_database=path, invite_tokens={"alice": SecretStr(secret)})
    app = create_app(settings, FakeProvider())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            body = report().model_dump(mode="json")
            assert (await client.post("/api/feedback", json=body)).status_code == 403
            client.headers["Origin"] = settings.allowed_origin
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
    with sqlite3.connect(path) as db:
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
