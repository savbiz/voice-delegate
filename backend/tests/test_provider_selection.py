"""Provider selection is server-gated, immutable per session and offline-testable."""

import pytest
from conftest import ASGIClientFactory
from pydantic import SecretStr
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import SessionError
from voice_delegate.session.preferences import VoicePreferences


async def test_independent_sessions_use_the_selected_provider() -> None:
    live, realtime = FakeProvider(), FakeProvider()
    realtime.model = "other-fake"
    manager = SessionManager(
        live,
        Settings(session_ui=True, cost_estimates=True),
        providers={"live": live, "realtime": realtime},
    )
    first = manager.create(preferences=VoicePreferences(adapter="live"))
    second = manager.create(preferences=VoicePreferences(adapter="realtime"))
    assert manager.config(first).model == "fake"
    assert manager.config(second).model == "other-fake"
    await manager.connect(first, "offer")
    await manager.connect(second, "offer")
    assert first.connection is live.connections[0]
    assert second.connection is realtime.connections[0]
    assert first.costs is not None and first.costs.adapter == "live"
    assert second.costs is not None and second.costs.adapter == "realtime"
    with pytest.raises(SessionError, match="not enabled"):
        manager.create(preferences=VoicePreferences(adapter="azure"))
    await manager.aclose()


async def test_flag_off_rejects_selection_before_admission() -> None:
    manager = SessionManager(FakeProvider(), Settings())
    with pytest.raises(SessionError, match="not enabled"):
        manager.create(preferences=VoicePreferences(adapter="realtime"))
    assert not manager.sessions
    await manager.aclose()


async def test_config_exposes_only_enabled_adapters_and_sdk_route_is_scoped(
    asgi_client: ASGIClientFactory,
) -> None:
    app = create_app(Settings(session_ui=True, openai_api_key=SecretStr("fixture")), FakeProvider())
    async with asgi_client(app) as client:
        client.headers["Origin"] = "http://localhost:5173"
        default = (await client.post("/api/config")).json()
        assert default["session_ui"]
        assert set(default["available_adapters"]) == {"live", "realtime"}
        assert (await client.post("/api/config", json={"adapter": "elevenlabs"})).status_code == 422
        selected = (await client.post("/api/config", json={"adapter": "realtime"})).json()
        assert selected["adapter"] == "realtime" and selected["transport"] == "webrtc"
        created = (await client.post("/api/sessions", json={"adapter": "live"})).json()
        client.headers["X-Session-Key"] = created["key"]
        assert (
            await client.post("/api/sessions/" + created["id"] + "/elevenlabs/bootstrap")
        ).status_code == 501
