"""API documentation is opt-in in production and available during development."""

from pathlib import Path

import pytest
from conftest import ASGIClientFactory, PublicSettingsFactory
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider


@pytest.mark.parametrize(
    ("production", "enabled", "expected"),
    [(True, False, 404), (True, True, 200), (False, False, 200), (False, True, 200)],
)
async def test_documentation_exposure(
    production: bool,
    enabled: bool,
    expected: int,
    tmp_path: Path,
    public_settings: PublicSettingsFactory,
    asgi_client: ASGIClientFactory,
) -> None:
    settings = (
        public_settings(tmp_path, api_docs=enabled, feedback_database=str(tmp_path / "feedback.db"))
        if production
        else Settings(api_docs=enabled)
    )
    app = create_app(settings, FakeProvider())
    async with asgi_client(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            response = await client.get(path)
            assert response.status_code == expected
        assert (await client.get("/healthz")).status_code == 200


def test_api_docs_environment_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_API_DOCS", "true")
    assert Settings().api_docs
