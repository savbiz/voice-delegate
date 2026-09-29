"""Keep the complete settings reference synchronized without reading configured secrets."""

import pytest

from scripts.build_configuration import OUTPUT, build


def test_configuration_reference_is_current_and_independent_of_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "private-value-never-document")
    monkeypatch.setenv("VOICE_MAX_SESSIONS", "99")
    rendered = build()
    assert "private-value-never-document" not in rendered
    assert OUTPUT.read_text() == rendered
