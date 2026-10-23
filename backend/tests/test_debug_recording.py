"""Debug content is recorded only with server permission and per-session consent."""

import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from conftest import ASGIClientFactory
from pydantic import SecretStr, ValidationError
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.debug import MAX_BYTES, RETENTION_SECONDS, DebugRecording, purge_recordings
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import DelegationRequested, Transcript

from test_support import eventually


@pytest.mark.parametrize(
    ("enabled", "consent", "status"), [(False, True, 403), (True, False, 201), (True, True, 201)]
)
async def test_recording_requires_both_gates_and_ownership(
    enabled: bool,
    consent: bool,
    status: int,
    tmp_path: Path,
    asgi_client: ASGIClientFactory,
) -> None:
    provider = FakeProvider()
    settings = Settings(
        debug_recording=enabled,
        debug_directory=str(tmp_path),
        access_token=SecretStr("local-placeholder"),
    )
    async with asgi_client(create_app(settings, provider)) as client:
        client.headers.update(
            {"Origin": settings.allowed_origin, "Authorization": "Bearer local-placeholder"}
        )
        assert (await client.post("/api/config")).json()["debug_recording_available"] is enabled
        response = await client.post("/api/sessions", json={"debug_recording": consent})
        assert response.status_code == status
        if status != 201:
            assert not await asyncio.to_thread(lambda: list(tmp_path.glob("*.jsonl")))
            return
        data = response.json()
        path = f"/api/sessions/{data['id']}"
        assert (await client.post(path + "/debug", json={"event": "stats"})).status_code == 404
        client.headers["X-Session-Key"] = data["key"]
        assert (
            await client.post(
                path + "/debug", json={"event": "stats", "authorization": "forbidden"}
            )
        ).status_code == 422
        sample = await client.post(path + "/debug", json={"event": "stats", "packets_lost": 2})
        assert sample.status_code == (200 if consent else 403)
        assert (await client.post(path + "/offer", json={"sdp": "v=0\r\n"})).status_code == 200
        provider.connections[0].queue.put_nowait(Transcript("user", "test conversation", 1, 10))
        provider.connections[0].queue.put_nowait(
            DelegationRequested("debug-task", goal="calculate 4+4")
        )
        await eventually(lambda: bool(provider.connections[0].commands))
        if consent:
            target = tmp_path / f"{data['id']}.jsonl"
            await eventually(lambda: "test conversation" in target.read_text())
        assert (await client.post(path + "/close")).status_code == 200
        files = await asyncio.to_thread(lambda: list(tmp_path.glob("*.jsonl")))
        assert len(files) == int(consent)
        if consent:
            text = files[0].read_text()
            rows = [json.loads(line) for line in text.splitlines()]
            assert rows[0]["event"] == "consent"
            assert rows[-1]["event"] == "closed"
            finished = [row for row in rows if row["event"] == "delegation_finished"]
            assert len(finished) == 1
            assert finished[0]["status"] == "completed"
            assert finished[0]["text"]
            assert "local-placeholder" not in text and data["key"] not in text
            assert files[0].stat().st_mode & 0o777 == 0o600


def test_production_rejects_debug_recording() -> None:
    with pytest.raises(ValidationError, match="only available in development"):
        Settings(environment="production", debug_recording=True)


def test_recording_is_bounded_and_expired_files_are_removed(tmp_path: Path) -> None:
    recording = DebugRecording(tmp_path, "test")
    recording.write("transcript", text="x" * MAX_BYTES)
    assert recording.stopped
    assert recording.path.stat().st_size <= MAX_BYTES
    old = time.time() - RETENTION_SECONDS - 1
    os.utime(recording.path, (old, old))
    purge_recordings(tmp_path)
    assert not recording.path.exists()


def test_storage_error_stops_recording_without_logging_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    recording = DebugRecording(tmp_path, "test")
    recording.path.unlink()
    recording.path.mkdir()
    recording.write("transcript", text="private-content")
    assert recording.stopped
    assert "private-content" not in caplog.text
