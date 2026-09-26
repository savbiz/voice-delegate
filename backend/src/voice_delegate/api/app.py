"""FastAPI factory owning provider clients, session cleanup, and browser API access."""

import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from importlib.metadata import version

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner, OpenAIPlanner

from voice_delegate.config import Settings, load_settings
from voice_delegate.feedback import FeedbackStore
from voice_delegate.limits.http import BodyLimitMiddleware
from voice_delegate.limits.ratelimit import RateLimitMiddleware
from voice_delegate.observability.metrics import Metrics, configure_metrics
from voice_delegate.observability.tracing import configure_tracing, get_tracer
from voice_delegate.providers.azure import AzureRealtimeProvider
from voice_delegate.providers.base import RealtimeProvider
from voice_delegate.providers.models import ProviderError, UnsupportedCapability
from voice_delegate.providers.openai import OpenAILiveProvider
from voice_delegate.providers.realtime import OpenAIRealtimeProvider
from voice_delegate.scaling.remote import RemoteWorker
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import SessionError

from .routes import build_router


def create_app(
    settings: Settings | None = None, provider: RealtimeProvider | None = None
) -> FastAPI:
    """Build a single-process app; inject an offline provider in tests."""
    settings = settings or load_settings()
    if provider is None:
        if settings.voice_provider == "azure":
            azure = AzureRealtimeProvider(
                settings.azure_endpoint, settings.azure_api_key.get_secret_value()
            )
            azure.model, azure.voice = settings.azure_deployment, settings.azure_voice
            provider = azure
        elif settings.voice_provider == "realtime":
            realtime = OpenAIRealtimeProvider(settings.openai_api_key.get_secret_value())
            realtime.model, realtime.voice = settings.realtime_model, settings.voice
            provider = realtime
        else:
            live = OpenAILiveProvider(
                settings.openai_api_key.get_secret_value(), settings.close_timeout_seconds
            )
            live.model, live.voice = settings.model, settings.voice
            provider = live
    fallback = None
    if settings.fallback_enabled:
        fallback = AzureRealtimeProvider(
            settings.azure_endpoint, settings.azure_api_key.get_secret_value()
        )
        fallback.model, fallback.voice = settings.azure_deployment, settings.azure_voice
    telemetry = configure_tracing(settings)
    meter_provider = configure_metrics(settings)
    planner = (
        None
        if settings.worker_execution == "remote"
        else (
            OpenAIPlanner(settings.openai_api_key.get_secret_value(), settings.worker_model)
            if settings.worker_mode == "openai"
            else OfflinePlanner()
        )
    )
    remote = RemoteWorker(settings) if settings.worker_execution == "remote" else None
    # SQLite calls are synchronous by design for the single-process demo.
    feedback = (
        FeedbackStore(settings.feedback_database)
        if settings.invite_tokens or settings.access_token.get_secret_value()
        else None
    )

    async def clean_feedback() -> None:
        while True:
            await asyncio.sleep(3600)
            if feedback is not None:
                try:
                    feedback.purge()
                except sqlite3.Error:
                    logging.getLogger(__name__).warning("Feedback cleanup unavailable; retrying")

    manager = SessionManager(
        provider,
        settings,
        tracer=get_tracer(telemetry),
        metrics=Metrics(meter_provider),
        worker=remote or LangGraphWorker(planner or OfflinePlanner(), settings.worker_max_steps),
        fallback=fallback,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        janitor = asyncio.create_task(manager.sweep(), name="session-janitor")
        feedback_janitor = asyncio.create_task(clean_feedback(), name="feedback-janitor")
        try:
            yield
        finally:
            janitor.cancel()
            feedback_janitor.cancel()
            with suppress(asyncio.CancelledError):
                await feedback_janitor
            if feedback is not None:
                feedback.close()
            with suppress(asyncio.CancelledError):
                await janitor
            await manager.aclose()
            if remote is not None:
                await remote.aclose()
            if isinstance(planner, OpenAIPlanner):
                await planner.aclose()
            if meter_provider is not None:
                await asyncio.to_thread(meter_provider.shutdown)
            if telemetry is not None:
                await asyncio.to_thread(telemetry.shutdown)

    app = FastAPI(title="voice-delegate", version=version("voice-delegate"), lifespan=lifespan)
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.allowed_origin],
        allow_methods=["POST"],
        allow_headers=["Content-Type", "X-Session-Key", "Authorization"],
    )
    # Wrap CORS too: preflights must pass host validation and consume the same IP budget.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        RateLimitMiddleware,
        trust_proxy=settings.trust_proxy,
        trusted_proxy_hops=settings.trusted_proxy_hops,
        allowed_origin=settings.allowed_origin,
    )

    @app.exception_handler(SessionError)
    async def session_error(_request: Request, exc: SessionError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(ProviderError)
    async def provider_error(_request: Request, exc: ProviderError) -> JSONResponse:
        status = 501 if isinstance(exc, UnsupportedCapability) else 502
        return JSONResponse({"detail": str(exc)}, status_code=status)

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(build_router(manager, feedback))
    return app
