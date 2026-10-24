"""The simulated provider is available only through an explicit test opt-in."""

import asyncio

import pytest
from conftest import ASGIClientFactory
from voice_delegate.config import Settings
from voice_delegate.scaling.scripted_app import create_test_app


@pytest.mark.parametrize("value", [None, "0", "true"])
def test_scripted_app_requires_exact_opt_in(
    value: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VOICE_SCRIPTED_PROVIDER", raising=False)
    if value is not None:
        monkeypatch.setenv("VOICE_SCRIPTED_PROVIDER", value)
    with pytest.raises(ValueError, match="VOICE_SCRIPTED_PROVIDER=1"):
        create_test_app()


async def test_scripted_app_starts_with_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, asgi_client: ASGIClientFactory
) -> None:
    monkeypatch.setenv("VOICE_SCRIPTED_PROVIDER", "1")
    monkeypatch.setattr("voice_delegate.scaling.scripted_app.load_settings", lambda: Settings())
    async with asgi_client(create_test_app()) as client:
        assert (await client.get("/healthz")).status_code == 200


@pytest.mark.parametrize(
    "mode", ["disabled", "paid_worker", "provider_key", "recording", "fallback"]
)
def test_demo_factory_refuses_paid_or_recorded_configuration(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import SecretStr
    from voice_delegate.scaling.scripted_app import create_demo_app

    monkeypatch.delenv("VOICE_OFFLINE_DEMO", raising=False)
    settings = Settings()
    if mode != "disabled":
        monkeypatch.setenv("VOICE_OFFLINE_DEMO", "1")
    if mode == "paid_worker":
        settings.worker_mode = "openai"
    if mode == "provider_key":
        settings.openai_api_key = SecretStr("not-a-real-key")
    if mode == "recording":
        settings.debug_recording = True
    if mode == "fallback":
        settings.fallback_enabled = True
    monkeypatch.setattr("voice_delegate.scaling.scripted_app.load_settings", lambda: settings)
    with pytest.raises(ValueError, match="Offline demo requires"):
        create_demo_app()


async def test_demo_runs_real_offline_worker_and_closes(
    monkeypatch: pytest.MonkeyPatch, asgi_client: ASGIClientFactory
) -> None:
    from voice_delegate.scaling.scripted_app import create_demo_app

    monkeypatch.setenv("VOICE_OFFLINE_DEMO", "1")
    monkeypatch.setattr("voice_delegate.scaling.scripted_app.load_settings", lambda: Settings())
    async with asgi_client(create_demo_app()) as client:
        client.headers["Origin"] = "http://localhost:5173"
        owner = (await client.post("/api/sessions")).json()
        path = f"/api/sessions/{owner['id']}"
        client.headers["X-Session-Key"] = owner["key"]
        assert (await client.post(path + "/offer", json={"sdp": "v=0\r\n"})).status_code == 200

        async def completed() -> bool:
            status = (await client.post(path + "/heartbeat")).json()
            return status["delegation"] == "completed" and "4" in status["recap"]["latest_reply"]

        for _ in range(100):
            if await completed():
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("Offline delegation did not complete")
        assert (await client.post(path + "/close")).json()["finalized"]
