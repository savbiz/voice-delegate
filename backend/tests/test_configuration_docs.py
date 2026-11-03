"""Keep the complete settings reference synchronized without reading configured secrets."""

import pytest
from voice_delegate.config import load_settings

from scripts.build_configuration import OUTPUT, build


def test_configuration_reference_is_current_and_independent_of_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "private-value-never-document")
    monkeypatch.setenv("VOICE_MAX_SESSIONS", "99")
    rendered = build()
    assert "private-value-never-document" not in rendered
    assert OUTPUT.read_text() == rendered


def test_server_template_boots_with_optional_features_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The published copyable baseline must validate without private credentials."""
    import os
    from pathlib import Path

    from dotenv import dotenv_values
    from pydantic import AliasChoices
    from voice_delegate.config import Settings

    for name in list(os.environ):
        if name.startswith("VOICE_") or name in {"OPENAI_API_KEY", "TAVILY_API_KEY"}:
            monkeypatch.delenv(name)
    values = dotenv_values(Path(__file__).resolve().parents[2] / ".env.example")
    for name, value in values.items():
        assert value is not None
        monkeypatch.setenv(name, value)
    canonical_names = set()
    for name, field in Settings.model_fields.items():
        alias = field.validation_alias
        canonical_names.add(
            alias.choices[0]
            if isinstance(alias, AliasChoices)
            else alias or "VOICE_" + name.upper()
        )
    canonical_names -= {
        "VOICE_ALLOWED_ORIGIN",
        "VOICE_COST_ESTIMATES",
        "VOICE_PRICE_FILE",
        "VOICE_SESSION_UI",
        "VOICE_ELEVENLABS_ENABLED",
        "ELEVENLABS_API_KEY",
        "VOICE_ELEVENLABS_AGENT_ID",
        "VOICE_ELEVENLABS_TIMEOUT_SECONDS",
        "VOICE_ELEVENLABS_WEBHOOK_TOKEN",
        "VOICE_ELEVENLABS_WEBHOOK_URL",
    }
    assert set(values) == canonical_names | {"BRAINTRUST_API_KEY", "VOICE_REALTIME_MODEL"}
    settings = Settings()
    assert settings.environment == "development"
    assert settings.worker_mode == "offline"
    assert settings.worker_execution == "local"
    assert settings.voice_provider == "openai"
    assert settings.worker_model == "gpt-6-luna"
    assert not settings.openai_api_key.get_secret_value()
    assert not settings.azure_api_key.get_secret_value()
    assert not settings.tavily_api_key.get_secret_value()
    assert not settings.access_token.get_secret_value()
    assert not settings.invite_tokens
    assert not any(
        (
            settings.fallback_enabled,
            settings.native_clients,
            settings.audio_timing,
            settings.intent_cancellation,
            settings.decisions_cancel,
            settings.web_search,
            settings.public_demo,
        )
    )


def test_automatic_debug_and_tracing_are_available_without_environment_flags() -> None:
    settings = load_settings()
    assert settings.debug_recording and settings.otel_enabled
