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
