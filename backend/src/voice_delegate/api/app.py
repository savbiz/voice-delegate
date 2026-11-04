"""FastAPI factory owning provider clients, session cleanup, and browser API access."""

import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from importlib.metadata import version

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner

from voice_delegate.access_request import AccessRequests, Approval
from voice_delegate.config import Settings, load_settings
from voice_delegate.delegation.planner import build_planner
from voice_delegate.feedback import FeedbackStore
from voice_delegate.limits.http import BodyLimitMiddleware
from voice_delegate.limits.ratelimit import RateLimitMiddleware
from voice_delegate.observability.metrics import Metrics, configure_metrics
from voice_delegate.observability.tracing import configure_tracing, get_tracer
from voice_delegate.providers.azure import AzureLiveProvider
from voice_delegate.providers.base import RealtimeProvider
from voice_delegate.providers.elevenlabs import ElevenLabsProvider
from voice_delegate.providers.models import ProviderError, UnsupportedCapability
from voice_delegate.providers.openai import OpenAILiveProvider
from voice_delegate.scaling.remote import RemoteWorker
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import SessionError

from .elevenlabs_webhook import build_webhook_router
from .notification_cors import NotificationActionCors, origin_of
from .routes import build_access_router, build_router


def create_app(
    settings: Settings | None = None,
    provider: RealtimeProvider | None = None,
    access_requests: AccessRequests | None = None,
) -> FastAPI:
    """Build a single-process app; inject an offline provider in tests."""
    settings = settings or load_settings()
    elevenlabs = (
        ElevenLabsProvider(
            settings.elevenlabs_api_key.get_secret_value(),
            settings.elevenlabs_agent_id,
            timeout=settings.elevenlabs_timeout_seconds,
            webhook_url=settings.elevenlabs_webhook_url,
        )
        if settings.elevenlabs_enabled
        else None
    )
    if provider is None:
        if settings.voice_provider == "elevenlabs":
            assert elevenlabs is not None
            provider = elevenlabs
        elif settings.voice_provider == "azure":
            azure = AzureLiveProvider(
                settings.azure_endpoint,
                settings.azure_api_key.get_secret_value(),
                close_timeout=settings.close_timeout_seconds,
            )
            azure.model, azure.voice = settings.azure_deployment, settings.azure_voice
            provider = azure
        else:
            live = OpenAILiveProvider(
                settings.openai_api_key.get_secret_value(), settings.close_timeout_seconds
            )
            live.model, live.voice = settings.model, settings.voice
            provider = live
    fallback = None
    if settings.fallback_enabled or (
        settings.session_ui
        and settings.azure_endpoint
        and settings.azure_api_key.get_secret_value()
    ):
        fallback = AzureLiveProvider(
            settings.azure_endpoint,
            settings.azure_api_key.get_secret_value(),
            close_timeout=settings.close_timeout_seconds,
        )
        fallback.model, fallback.voice = settings.azure_deployment, settings.azure_voice
    providers: dict[str, RealtimeProvider] = {settings.voice_provider: provider}
    if settings.session_ui:
        if settings.openai_api_key.get_secret_value() and "openai" not in providers:
            live = OpenAILiveProvider(
                settings.openai_api_key.get_secret_value(), settings.close_timeout_seconds
            )
            live.model, live.voice = settings.model, settings.voice
            providers["openai"] = live
        if (
            settings.azure_api_key.get_secret_value()
            and settings.azure_endpoint
            and "azure" not in providers
        ):
            azure = AzureLiveProvider(
                settings.azure_endpoint,
                settings.azure_api_key.get_secret_value(),
                close_timeout=settings.close_timeout_seconds,
            )
            azure.model, azure.voice = settings.azure_deployment, settings.azure_voice
            providers["azure"] = azure
        if (
            elevenlabs is not None
            and settings.intent_cancellation
            and settings.delegation_timeout_seconds + settings.delivery_timeout_seconds <= 110
        ):
            providers["elevenlabs"] = elevenlabs
    telemetry = configure_tracing(settings)
    meter_provider = configure_metrics(settings)
    runtime = build_planner(settings) if settings.worker_execution == "local" else None
    planner = runtime.planner if runtime is not None else None
    remote = RemoteWorker(settings) if settings.worker_execution == "remote" else None
    # SQLite calls are synchronous by design for the single-process demo.
    feedback = (
        FeedbackStore(settings.feedback_database)
        if settings.invite_tokens
        or settings.access_token.get_secret_value()
        or settings.public_demo
        or settings.public_api_url
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
        worker=remote
        or (
            runtime.worker(settings.worker_max_steps)
            if runtime is not None
            else LangGraphWorker(planner or OfflinePlanner(), settings.worker_max_steps)
        ),
        fallback=fallback,
        providers=providers,
    )

    if access_requests is not None and access_requests.store is not None:
        # An injected store (tests) replaces the one admission opened.
        if manager.admission.invites is not None:
            manager.admission.invites.close()
        manager.admission.invites = access_requests.store
    elif access_requests is None and settings.access_request_url:
        store = manager.admission.invites if settings.public_api_url else None
        access_requests = AccessRequests(
            settings.access_request_url,
            store=store,
            approval=Approval(
                public_api_url=settings.public_api_url.rstrip("/"),
                frontend_url=settings.allowed_origins[0],
            )
            if store is not None
            else None,
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
            if access_requests is not None:
                await access_requests.aclose()
            with suppress(asyncio.CancelledError):
                await janitor
            await manager.aclose()
            if elevenlabs is not None and "elevenlabs" not in providers:
                await elevenlabs.aclose()
            if remote is not None:
                await remote.aclose()
            if runtime is not None:
                await runtime.aclose()
            if meter_provider is not None:
                await asyncio.to_thread(meter_provider.shutdown)
            if telemetry is not None:
                await asyncio.to_thread(telemetry.shutdown)

    expose_docs = settings.environment != "production" or settings.api_docs
    app = FastAPI(
        title="voice-delegate",
        version=version("voice-delegate"),
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["POST"],
        allow_headers=["Content-Type", "X-Session-Key", "Authorization"],
    )
    if access_requests is not None and access_requests.store is not None:
        # Approve/Deny buttons in the ntfy web app call /access/ from the notification origin.
        app.add_middleware(NotificationActionCors, origin=origin_of(access_requests.url))
    # Wrap CORS too: preflights must pass host validation and consume the same IP budget.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        RateLimitMiddleware,
        trust_proxy=settings.trust_proxy,
        trusted_proxy_hops=settings.trusted_proxy_hops,
        allowed_origins=settings.allowed_origins,
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"detail": "Invalid request"}, status_code=422, headers={"Cache-Control": "no-store"}
        )

    @app.exception_handler(SessionError)
    async def session_error(_request: Request, exc: SessionError) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc)}, status_code=exc.status, headers={"Cache-Control": "no-store"}
        )

    @app.exception_handler(ProviderError)
    async def provider_error(_request: Request, exc: ProviderError) -> JSONResponse:
        status = 501 if isinstance(exc, UnsupportedCapability) else 502
        return JSONResponse(
            {"detail": str(exc)}, status_code=status, headers={"Cache-Control": "no-store"}
        )

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(build_router(manager, feedback, elevenlabs, access_requests))
    app.include_router(build_webhook_router(manager))
    if access_requests is not None and access_requests.store is not None:
        app.include_router(build_access_router(access_requests))
    return app
