"""The simulated provider is available only through an explicit test opt-in."""

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
