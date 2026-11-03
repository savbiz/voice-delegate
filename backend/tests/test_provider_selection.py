"""Provider selection is server-gated, immutable per session and offline-testable."""

import json
from pathlib import Path
from typing import Literal

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
        providers={"openai": live, "azure": realtime},
    )
    first = manager.create(preferences=VoicePreferences(adapter="openai"))
    second = manager.create(preferences=VoicePreferences(adapter="azure"))
    assert manager.config(first).model == "fake"
    assert manager.config(second).model == "other-fake"
    await manager.connect(first, "offer")
    await manager.connect(second, "offer")
    assert first.connection is live.connections[0]
    assert second.connection is realtime.connections[0]
    assert first.costs is not None and first.costs.adapter == "openai"
    assert second.costs is not None and second.costs.adapter == "azure"
    with pytest.raises(SessionError, match="not enabled"):
        manager.create(preferences=VoicePreferences(adapter="elevenlabs"))
    await manager.aclose()


async def test_flag_off_rejects_selection_before_admission() -> None:
    manager = SessionManager(FakeProvider(), Settings())
    with pytest.raises(SessionError, match="not enabled"):
        manager.create(preferences=VoicePreferences(adapter="azure"))
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
        assert set(default["available_adapters"]) == {"openai"}
        assert (await client.post("/api/config", json={"adapter": "elevenlabs"})).status_code == 422
        selected = (await client.post("/api/config", json={"adapter": "openai"})).json()
        assert selected["adapter"] == "openai" and selected["transport"] == "webrtc"
        created = (await client.post("/api/sessions", json={"adapter": "openai"})).json()
        client.headers["X-Session-Key"] = created["key"]
        assert (
            await client.post("/api/sessions/" + created["id"] + "/elevenlabs/bootstrap")
        ).status_code == 501


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost",
        "https://example.org",
        "https://resource.openai.azure.com/path",
        "https://user@resource.openai.azure.com",
        "https://resource.openai.azure.com:444",
    ],
)
def test_selectable_azure_requires_a_trusted_resource_origin(endpoint: str) -> None:
    with pytest.raises(ValueError, match="HTTPS Azure"):
        Settings(session_ui=True, azure_endpoint=endpoint, azure_api_key=SecretStr("fixture"))


@pytest.mark.parametrize("adapter", ["azure", "elevenlabs"])
async def test_non_openai_sessions_never_transition_to_azure_fallback(
    adapter: Literal["azure", "elevenlabs"],
) -> None:
    from voice_delegate.providers.models import ProviderFailure

    primary, fallback = FakeProvider(), FakeProvider()
    manager = SessionManager(
        primary,
        Settings(session_ui=True),
        fallback=fallback,
        providers={"openai": FakeProvider(), adapter: primary},
    )
    session = manager.create(preferences=VoicePreferences(adapter=adapter))
    await manager.connect(session, "v=0\r\n")
    with pytest.raises(SessionError) as error:
        await manager.reconnect(session, "v=0\r\n", 0)
    assert error.value.status == 501
    primary.connections[0].queue.put_nowait(ProviderFailure())
    assert session.watcher is not None
    await session.watcher
    assert session.state == "closed"
    assert not fallback.connections
    await manager.aclose()


def test_debug_recording_names_the_session_adapter(tmp_path: Path) -> None:
    live, azure = FakeProvider(), FakeProvider()
    manager = SessionManager(
        live,
        Settings(session_ui=True, debug_recording=True, debug_directory=str(tmp_path)),
        providers={"openai": live, "azure": azure},
    )
    session = manager.create(
        preferences=VoicePreferences(adapter="azure", debug_recording=True),
    )
    first = json.loads((tmp_path / f"{session.id}.jsonl").read_text().splitlines()[0])
    assert first["event"] == "consent"
    assert first["provider"] == "azure"
