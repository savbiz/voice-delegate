"""Offline validation and ownership checks for untrusted browser timing reports."""

import pytest
from conftest import ASGIClientFactory
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from voice_delegate.api.routes import build_router
from voice_delegate.config import Settings
from voice_delegate.observability.metrics import Metrics
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import SessionError


@pytest.mark.parametrize("enabled", [False, True])
async def test_timing_flag_ownership_validation_and_budget(
    asgi_client: ASGIClientFactory, enabled: bool
) -> None:
    manager = SessionManager(FakeProvider(), Settings(audio_timing=enabled))
    app = FastAPI()
    app.include_router(build_router(manager))

    @app.exception_handler(SessionError)
    async def session_error(_request: Request, error: SessionError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    async with asgi_client(app) as client:
        client.headers["Origin"] = "http://localhost:5173"
        assert (await client.post("/api/config")).json()["audio_timing_available"] is enabled
        created = (await client.post("/api/sessions")).json()
        path = f"/api/sessions/{created['id']}"
        body = {"kind": "setup", "seconds": 0.4, "generation": 0}
        assert (await client.post(path + "/audio-timing", json=body)).status_code == 404
        client.headers["X-Session-Key"] = created["key"]
        if enabled:
            assert (await client.post(path + "/audio-timing", json=body)).status_code == 409
        await client.post(path + "/offer", json={"sdp": "v=0\r\n"})
        response = await client.post(path + "/audio-timing", json=body)
        assert response.status_code == (200 if enabled else 403)
        if not enabled:
            await manager.aclose()
            return
        for invalid in (
            {"seconds": -1},
            {"seconds": 121},
            {"seconds": "NaN"},
            {"kind": "text"},
            {"text": "no"},
        ):
            assert (
                await client.post(path + "/audio-timing", json=body | invalid)
            ).status_code == 422
        assert (
            await client.post(path + "/audio-timing", json=body | {"generation": 1})
        ).status_code == 409
        # Check the per-session cap without hitting the independent per-IP limiter.
        manager.get(created["id"], created["key"]).audio_timing_samples = 120
        assert (await client.post(path + "/audio-timing", json=body)).status_code == 429
        await manager.aclose()


def test_audio_metric_has_only_finite_labels_and_seconds() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    try:
        Metrics(provider).audio_playback.record(0.4, {"kind": "turn"})
        data = reader.get_metrics_data()
        assert data is not None
        metric = data.resource_metrics[0].scope_metrics[0].metrics[0]
        assert metric.name == "voice.browser.audio_playback"
        assert metric.unit == "s"
        assert metric.data.data_points[0].attributes == {"kind": "turn"}
    finally:
        provider.shutdown()
