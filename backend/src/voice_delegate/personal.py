"""Ephemeral user-supplied provider access, isolated from platform clients and keys."""

import hashlib

from pydantic import Field, SecretStr

from voice_delegate.config import Settings
from voice_delegate.delegation.contracts import Worker
from voice_delegate.delegation.planner import PlannerRuntime, build_planner
from voice_delegate.providers.azure import AzureLiveProvider
from voice_delegate.providers.base import RealtimeProvider
from voice_delegate.providers.elevenlabs import ElevenLabsProvider
from voice_delegate.providers.openai import OpenAILiveProvider
from voice_delegate.scaling.remote import RemoteWorker
from voice_delegate.session.access import PersonalKeys
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import Session, SessionError
from voice_delegate.session.preferences import VoicePreferences


class PersonalSession(VoicePreferences):
    keys: PersonalKeys = Field(repr=False)


async def create_personal_session(root: SessionManager, body: PersonalSession) -> Session:
    """Allocate only after local validation; no paid validation calls or persistent key store."""
    if root._shutting_down or len(root.sessions) >= root.settings.max_sessions:
        raise SessionError(429, "Session capacity reached")
    adapter = body.adapter or "openai"
    key = (
        body.keys.elevenlabs_key
        if adapter == "elevenlabs"
        else body.keys.azure_key
        if adapter == "azure"
        else body.keys.openai_key
    )
    if not key.get_secret_value():
        raise SessionError(422, "A personal key for the selected provider is required")
    if adapter == "elevenlabs" and len(body.keys.elevenlabs_webhook_token.get_secret_value()) < 32:
        raise SessionError(422, "The ElevenLabs webhook token must contain at least 32 characters")
    principal = "personal:" + hashlib.sha256(key.get_secret_value().encode()).hexdigest()
    if any(s.principal == principal for s in root.sessions.values()):
        raise SessionError(429, "A personal conversation is already active")
    supplied = body.keys.worker_settings(root.settings)
    data = supplied.model_dump()
    data.update(
        voice_provider=adapter,
        environment="development",
        public_demo=False,
        invite_tokens={},
        access_token=SecretStr(""),
        fallback_enabled=body.azure_recovery,
        debug_recording=True,
        session_ui=True,
        intent_cancellation=True,
        native_clients=False,
        elevenlabs_enabled=adapter == "elevenlabs",
    )
    try:
        settings = Settings.model_validate(data)
    except ValueError:
        raise SessionError(
            422, "Personal provider configuration is incomplete or invalid"
        ) from None
    provider: RealtimeProvider
    if adapter == "elevenlabs":
        provider = ElevenLabsProvider(
            key.get_secret_value(),
            settings.elevenlabs_agent_id,
            timeout=settings.elevenlabs_timeout_seconds,
            webhook_url=settings.elevenlabs_webhook_url,
        )
    elif adapter == "azure":
        azure = AzureLiveProvider(
            settings.azure_endpoint,
            key.get_secret_value(),
            close_timeout=settings.close_timeout_seconds,
        )
        azure.model, azure.voice = settings.azure_deployment, settings.azure_voice
        provider = azure
    else:
        live = OpenAILiveProvider(key.get_secret_value(), settings.close_timeout_seconds)
        live.model, live.voice = settings.model, settings.voice
        provider = live
    fallback = None
    if body.azure_recovery:
        if adapter != "openai":
            await provider.aclose()
            raise SessionError(422, "Azure recovery requires an OpenAI primary session")
        fallback = AzureLiveProvider(
            settings.azure_endpoint,
            settings.azure_api_key.get_secret_value(),
            close_timeout=settings.close_timeout_seconds,
        )
        fallback.model, fallback.voice = settings.azure_deployment, settings.azure_voice
    runtime: PlannerRuntime | None = None
    remote: RemoteWorker | None = None
    worker: Worker
    owner: SessionManager | None = None

    async def dispose(current: SessionManager | None) -> None:
        try:
            if current is not None:
                await current.aclose()
            else:
                try:
                    await provider.aclose()
                finally:
                    if fallback is not None:
                        await fallback.aclose()
        finally:
            try:
                if runtime is not None:
                    await runtime.aclose()
            finally:
                if remote is not None:
                    await remote.aclose()

    try:
        if settings.worker_execution == "remote":
            remote = RemoteWorker(settings, personal_keys=body.keys)
            worker = remote
        else:
            runtime = build_planner(settings)
            worker = runtime.worker(settings.worker_max_steps)
        owner = SessionManager(
            provider,
            settings,
            worker=worker,
            metrics=root.metrics,
            clock=root.clock,
            fallback=fallback,
        )
        preferences = VoicePreferences.model_validate(body.model_dump(exclude={"keys"}))
        session = owner.create(principal, preferences)
        root.admission.reserve_personal(principal, session.id)
    except BaseException:
        await dispose(owner)
        raise
    managed = owner

    async def release() -> None:
        root.sessions.pop(session.id, None)
        root.admission.release(session.id)
        session.owner = None
        session.release_personal = None
        await dispose(managed)

    session.owner = managed
    session.release_personal = release
    root.sessions[session.id] = session
    return session
