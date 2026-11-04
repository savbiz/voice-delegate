"""Local-demo HTTP routes with per-session ownership and origin validation."""

from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from voice_delegate_agent.limits import QUERY_MAX_CHARS
from voice_delegate_agent.reference import search, source_by_id

from voice_delegate.access_request import AccessRequestInput, AccessRequests
from voice_delegate.debug import DebugSample
from voice_delegate.feedback import FeedbackInput, FeedbackStore
from voice_delegate.personal import PersonalSession, create_personal_session
from voice_delegate.providers.elevenlabs import ElevenLabsProvider
from voice_delegate.providers.elevenlabs_session import ElevenLabsConnection
from voice_delegate.providers.models import SpeechStarted, Transcript, UnsupportedCapability
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import Session
from voice_delegate.session.preferences import VoicePreferences

from .schemas import (
    Activity,
    Answer,
    AudioTiming,
    Cancellation,
    Closed,
    Created,
    Offer,
    Reconnect,
    Status,
    TaskStatus,
)


class SDKEvent(BaseModel):
    """Owner-authenticated SDK reports; no arbitrary provider commands or tool names."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["connected", "transcript", "activity"]
    sequence: int = Field(ge=0, le=1000000)
    conversation_id: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=8192)
    speaker: Literal["user", "assistant"] = "user"
    user_speaking: bool = False
    assistant_speaking: bool = False


class ReferenceQuery(BaseModel):
    query: str = Field(min_length=1, max_length=QUERY_MAX_CHARS)


def build_access_router(access_requests: AccessRequests) -> APIRouter:
    """Owner decisions from notification buttons; the one-time secret is the credential."""
    router = APIRouter(prefix="/access")
    RequestId = Annotated[str, Path(min_length=8, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")]
    Secret = Annotated[str, Path(min_length=32, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]

    @router.post("/{request_id}/{secret}/approve")
    async def approve(request_id: RequestId, secret: Secret, response: Response) -> dict[str, str]:
        response.headers["Cache-Control"] = "no-store"
        await access_requests.approve(request_id, secret)
        return {"status": "approved"}

    @router.post("/{request_id}/{secret}/deny")
    async def deny(request_id: RequestId, secret: Secret, response: Response) -> dict[str, str]:
        response.headers["Cache-Control"] = "no-store"
        access_requests.deny(request_id, secret)
        return {"status": "denied"}

    return router


def build_router(
    manager: SessionManager,
    feedback: FeedbackStore | None = None,
    elevenlabs: ElevenLabsProvider | None = None,
    access_requests: AccessRequests | None = None,
) -> APIRouter:
    """Bind a router to one lifecycle-owned manager, avoiding untyped app state."""

    root = manager

    async def check_origin(request: Request, response: Response) -> None:
        if request.headers.get("origin") not in manager.settings.allowed_origins:
            raise HTTPException(403, "Unexpected request origin")
        response.headers["Cache-Control"] = "no-store"

    router = APIRouter(prefix="/api", dependencies=[Depends(check_origin)])

    async def authorize(request: Request) -> str:
        return manager.admission.authenticate(request.headers.get("authorization", ""))

    @router.post("/feedback", status_code=201)
    async def submit_feedback(
        body: FeedbackInput, principal: Annotated[str, Depends(authorize)]
    ) -> dict[str, str]:
        if feedback is None:
            raise HTTPException(503, "Feedback requires a configured invitation or access code")
        provider = body.adapter if body.adapter in manager.providers else None
        provider = provider or manager.settings.voice_provider
        return {"diagnostic_id": feedback.submit(principal, body, provider)}

    @router.post("/access-request", status_code=202)
    async def request_access(body: AccessRequestInput) -> dict[str, str]:
        if access_requests is None:
            raise HTTPException(503, "Access requests are not enabled on this server")
        await access_requests.submit(body)
        return {"status": "sent"}

    @router.post("/config")
    async def configuration(body: VoicePreferences | None = None) -> dict[str, object]:
        adapter = manager.select_adapter(body.adapter if body else None)
        return {
            "adapter": adapter,
            "session_ui": manager.settings.session_ui,
            "available_adapters": list(manager.providers) if manager.settings.session_ui else [],
            "transport": "elevenlabs_agents_webrtc" if adapter == "elevenlabs" else "webrtc",
            "audio_recording_available": adapter != "elevenlabs",
            "azure_recovery_available": manager.fallback is not None,
            "debug_recording_available": manager.settings.debug_recording,
            "audio_timing_available": manager.settings.audio_timing,
            "intent_cancellation": manager.settings.intent_cancellation,
            "feedback_available": feedback is not None,
            "access_request_available": access_requests is not None,
            "access_request_email": access_requests is not None and access_requests.requires_email,
            "requires_access_code": bool(
                manager.settings.invite_tokens
                or manager.settings.access_token.get_secret_value()
                or manager.admission.invites is not None
            ),
            "voice_available": bool(
                manager.settings.elevenlabs_api_key.get_secret_value()
                if adapter == "elevenlabs"
                else manager.settings.azure_api_key.get_secret_value()
                if adapter == "azure"
                else manager.settings.openai_api_key.get_secret_value()
            ),
        }

    async def owned(
        session_id: str,
        request: Request,
        x_session_key: Annotated[str, Header()] = "",
    ) -> Session:
        session = root.get(session_id, x_session_key)
        if session.owner is None:
            principal = await authorize(request)
            if session.principal != principal:
                raise HTTPException(404, "Session not found")
        return session

    @router.post("/personal/config")
    async def personal_configuration(body: VoicePreferences | None = None) -> dict[str, object]:
        adapter = body.adapter if body and body.adapter else "openai"
        available = ["openai", "azure"]
        if root.settings.elevenlabs_webhook_url:
            available.append("elevenlabs")
        if adapter not in available:
            raise HTTPException(422, "Personal provider is unavailable")
        return {
            "adapter": adapter,
            "available_adapters": available,
            "session_ui": True,
            "voice_available": True,
            "azure_recovery_available": adapter == "openai",
            "intent_cancellation": True,
            "audio_timing_available": root.settings.audio_timing,
            "debug_recording_available": True,
            "audio_recording_available": adapter != "elevenlabs",
            "transport": "elevenlabs_agents_webrtc" if adapter == "elevenlabs" else "webrtc",
            "elevenlabs_webhook_url": root.settings.elevenlabs_webhook_url,
        }

    @router.post("/personal/sessions", status_code=201)
    async def personal_create(body: PersonalSession, request: Request) -> Created:
        if body.adapter == "elevenlabs" and request.headers.get("origin") in {
            "capacitor://localhost",
            "https://localhost",
        }:
            raise HTTPException(422, "ElevenLabs is available in browsers only")
        session = await create_personal_session(root, body)
        return Created(
            id=session.id, key=session.key, ttl_seconds=root.settings.session_ttl_seconds
        )

    @router.post("/reference/search")
    async def reference_search(
        body: ReferenceQuery, _: Annotated[str, Depends(authorize)]
    ) -> dict[str, object]:
        sources = search(body.query)
        return {
            "sources": [asdict(source) for source in sources],
            "status": "found" if sources else "No supporting documentation found.",
        }

    @router.post("/reference/{source_id}")
    async def reference_source(
        source_id: str, _: Annotated[str, Depends(authorize)]
    ) -> dict[str, str]:
        source = source_by_id(source_id)
        if source is None:
            raise HTTPException(404, "Source not found")
        return asdict(source)

    @router.post("/sessions", status_code=201)
    async def create(
        principal: Annotated[str, Depends(authorize)],
        request: Request,
        body: VoicePreferences | None = None,
    ) -> Created:
        adapter = manager.select_adapter(body.adapter if body else None)
        if adapter == "elevenlabs" and request.headers.get("origin") in {
            "capacitor://localhost",
            "https://localhost",
        }:
            raise HTTPException(422, "ElevenLabs is available in browsers only")
        session = manager.create(principal, body)
        return Created(
            id=session.id, key=session.key, ttl_seconds=manager.settings.session_ttl_seconds
        )

    @router.post("/sessions/{session_id}/debug")
    async def record_debug(
        body: DebugSample, session: Annotated[Session, Depends(owned)]
    ) -> dict[str, bool]:
        manager = root.owner_for(session)
        if session.debug is None:
            raise HTTPException(403, "Debug recording was not enabled for this session")
        session.debug.write(
            "browser_" + body.event,
            worker_state=session.portfolio.status
            if manager.settings.intent_cancellation
            else session.delegation.status,
            **body.model_dump(exclude={"event"}),
        )
        return {"recording": not session.debug.stopped}

    @router.post("/sessions/{session_id}/audio-timing")
    async def audio_timing(
        body: AudioTiming, session: Annotated[Session, Depends(owned)]
    ) -> dict[str, bool]:
        manager = root.owner_for(session)
        if not manager.settings.audio_timing:
            raise HTTPException(403, "Audio timing is disabled")
        if session.state != "connected" or body.generation != session.generation:
            raise HTTPException(409, "Audio timing requires the current connected transport")
        if session.audio_timing_samples >= 120:
            raise HTTPException(429, "Audio timing sample limit reached")
        session.audio_timing_samples += 1
        manager.metrics.audio_playback.record(body.seconds, {"kind": body.kind})
        return {"recorded": True}

    @router.post("/sessions/{session_id}/activity")
    async def activity(
        body: Activity, session: Annotated[Session, Depends(owned)]
    ) -> dict[str, bool]:
        manager = root.owner_for(session)
        if not manager.settings.intent_cancellation:
            raise HTTPException(403, "Intent cancellation is disabled")
        if session.state != "connected" or body.generation != session.generation:
            raise HTTPException(409, "Activity requires the current connected transport")
        manager.intent.activity(
            session.portfolio,
            body.sequence,
            speaking=body.user_speaking or body.assistant_speaking,
            assistant_speaking=body.assistant_speaking,
        )
        return {"recorded": True}

    @router.post("/sessions/{session_id}/offer")
    async def offer(body: Offer, session: Annotated[Session, Depends(owned)]) -> Answer:
        manager = root.owner_for(session)
        result = await manager.connect(session, body.sdp)
        return Answer(sdp=result.sdp)

    @router.post("/sessions/{session_id}/reconnect")
    async def reconnect(body: Reconnect, session: Annotated[Session, Depends(owned)]) -> Answer:
        manager = root.owner_for(session)
        result = await manager.reconnect(session, body.sdp, body.generation)
        return Answer(sdp=result.sdp)

    @router.post("/sessions/{session_id}/heartbeat")
    async def heartbeat(session: Annotated[Session, Depends(owned)]) -> Status:
        manager = root.owner_for(session)
        manager.heartbeat(session)
        return Status(
            state=session.state,
            delegation=session.portfolio.status
            if manager.settings.intent_cancellation
            else session.delegation.status,
            tasks=[
                TaskStatus(
                    id=j.id,
                    goal=j.goal,
                    status=j.status,
                    work_seconds=j.durations(manager.clock())[0],
                    delivery_wait_seconds=j.durations(manager.clock())[1],
                    elapsed_seconds=max(
                        0, (j.finished if j.finished is not None else manager.clock()) - j.started
                    ),
                )
                for j in session.portfolio.jobs.values()
            ],
            costs=session.costs.snapshot() if session.costs else None,
            decision_cost_usd=session.portfolio.decision_cost,
            generation=session.generation,
            sources=session.portfolio.sources
            if manager.settings.intent_cancellation
            else session.delegation.sources,
            recap=session.recap,
            fallback_available=manager.fallback is not None
            and session.adapter == "openai"
            and session.preferences.azure_recovery
            and not session.fallback_used,
        )

    @router.post("/sessions/{session_id}/close")
    async def close(session: Annotated[Session, Depends(owned)]) -> Closed:
        manager = root.owner_for(session)
        finalized = await manager.close(session)
        return Closed(
            finalized=finalized, costs=session.costs.snapshot() if session.costs else None
        )

    @router.post("/sessions/{session_id}/interrupt")
    async def interrupt(
        session: Annotated[Session, Depends(owned)], body: Cancellation | None = None
    ) -> dict[str, str]:
        manager = root.owner_for(session)
        manager.interrupt(session, task_id=body.task_id if body else None)
        return {
            "delegation": session.portfolio.status
            if manager.settings.intent_cancellation
            else session.delegation.status
        }

    @router.post("/sessions/{session_id}/elevenlabs/bootstrap")
    async def elevenlabs_bootstrap(session: Annotated[Session, Depends(owned)]) -> dict[str, str]:
        manager = root.owner_for(session)
        selected = manager.provider_for(session)
        if session.owner is not None:
            selected_elevenlabs = selected if isinstance(selected, ElevenLabsProvider) else None
        else:
            selected_elevenlabs = elevenlabs
        if selected_elevenlabs is None or session.adapter != "elevenlabs":
            raise HTTPException(501, "ElevenLabs preview is disabled")
        async with session.lock:
            if session.state != "created" or session.sdk_bootstrap_issued:
                raise HTTPException(409, "Session setup already attempted")
            # Do not retry a token mint after an ambiguous upstream failure.
            session.sdk_bootstrap_issued = True
            session.state = "connecting"
            # Credential issuance does not confirm upstream media closure.
            session.previous_finalized = False
            with manager.metrics.operation("provider.connect"):
                await selected_elevenlabs.validate_agent(manager.settings.session_ttl_seconds)
                bootstrap = await selected_elevenlabs.prepare_browser()

            async def confirm_close() -> bool:
                return await selected_elevenlabs.confirm_closed(
                    bootstrap.conversation_id,
                    session.costs.report_provider_usage if session.costs is not None else None,
                )

            session.connection = ElevenLabsConnection(bootstrap.conversation_id, confirm_close)
            session.previous_finalized = True
            return {
                "transport": bootstrap.transport,
                "conversation_id": bootstrap.conversation_id,
                "token": bootstrap.token,
            }

    def sdk_connection(session: Session) -> ElevenLabsConnection:
        if not isinstance(session.connection, ElevenLabsConnection) or session.connection.closed:
            raise HTTPException(409, "SDK transport is not active")
        return session.connection

    @router.post("/sessions/{session_id}/elevenlabs/events")
    async def sdk_event(
        body: SDKEvent, session: Annotated[Session, Depends(owned)]
    ) -> dict[str, bool]:
        manager = root.owner_for(session)
        connection = sdk_connection(session)
        if body.sequence <= connection.sequence:
            return {"recorded": False}
        if connection.events_received >= 4096:
            raise HTTPException(429, "SDK event budget reached")
        if body.kind == "connected":
            if body.conversation_id != connection.conversation_id:
                raise HTTPException(409, "SDK conversation identity mismatch")
            if session.state not in {"connecting", "connected"}:
                raise HTTPException(409, "SDK transport cannot attach in this session state")
            if not connection.started:
                if session.state != "connecting":
                    raise HTTPException(409, "SDK transport is not awaiting connection")
                connection.start()
                manager.attach_sdk(session, connection)
        elif not connection.started or session.state != "connected":
            raise HTTPException(409, "SDK transport is not connected")
        elif body.kind == "transcript":
            if body.speaker == "user":
                connection.emit(SpeechStarted())
            connection.emit(Transcript(body.speaker, body.text, 0, 0, committed=True))
        elif manager.settings.intent_cancellation:
            manager.intent.activity(
                session.portfolio,
                body.sequence,
                speaking=body.user_speaking or body.assistant_speaking,
                assistant_speaking=body.assistant_speaking,
            )
        connection.sequence = body.sequence
        connection.events_received += 1
        return {"recorded": True}

    @router.post("/sessions/{session_id}/token")
    async def token(_session: Annotated[Session, Depends(owned)]) -> None:
        message = "GPT-Live uses /offer; ephemeral credentials are unsupported"
        raise UnsupportedCapability(message)

    return router
