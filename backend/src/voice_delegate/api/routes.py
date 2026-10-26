"""Local-demo HTTP routes with per-session ownership and origin validation."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from voice_delegate_agent.limits import QUERY_MAX_CHARS
from voice_delegate_agent.reference import search, source_by_id

from voice_delegate.debug import DebugSample
from voice_delegate.feedback import FeedbackInput, FeedbackStore
from voice_delegate.providers.models import UnsupportedCapability
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


class ReferenceQuery(BaseModel):
    query: str = Field(min_length=1, max_length=QUERY_MAX_CHARS)


def build_router(manager: SessionManager, feedback: FeedbackStore | None = None) -> APIRouter:
    """Bind a router to one lifecycle-owned manager, avoiding untyped app state."""

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
        return {"diagnostic_id": feedback.submit(principal, body, manager.settings.voice_provider)}

    @router.post("/config")
    async def configuration() -> dict[str, bool]:
        return {
            "debug_recording_available": manager.settings.debug_recording,
            "audio_timing_available": manager.settings.audio_timing,
            "intent_cancellation": manager.settings.intent_cancellation,
            "feedback_available": feedback is not None,
            "requires_access_code": bool(
                manager.settings.invite_tokens or manager.settings.access_token.get_secret_value()
            ),
            "voice_available": bool(
                manager.settings.azure_api_key.get_secret_value()
                if manager.settings.voice_provider == "azure"
                else manager.settings.openai_api_key.get_secret_value()
            ),
        }

    async def owned(
        session_id: str,
        principal: Annotated[str, Depends(authorize)],
        x_session_key: Annotated[str, Header()] = "",
    ) -> Session:
        session = manager.get(session_id, x_session_key)
        if session.principal != principal:
            raise HTTPException(404, "Session not found")
        return session

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
        principal: Annotated[str, Depends(authorize)], body: VoicePreferences | None = None
    ) -> Created:
        session = manager.create(principal, body)
        return Created(
            id=session.id, key=session.key, ttl_seconds=manager.settings.session_ttl_seconds
        )

    @router.post("/sessions/{session_id}/debug")
    async def record_debug(
        body: DebugSample, session: Annotated[Session, Depends(owned)]
    ) -> dict[str, bool]:
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
        result = await manager.connect(session, body.sdp)
        return Answer(sdp=result.sdp)

    @router.post("/sessions/{session_id}/reconnect")
    async def reconnect(body: Reconnect, session: Annotated[Session, Depends(owned)]) -> Answer:
        result = await manager.reconnect(session, body.sdp, body.generation)
        return Answer(sdp=result.sdp)

    @router.post("/sessions/{session_id}/heartbeat")
    async def heartbeat(session: Annotated[Session, Depends(owned)]) -> Status:
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
            decision_cost_usd=session.portfolio.decision_cost,
            generation=session.generation,
            sources=session.portfolio.sources
            if manager.settings.intent_cancellation
            else session.delegation.sources,
            recap=session.recap,
            fallback_available=manager.fallback is not None and not session.fallback_used,
        )

    @router.post("/sessions/{session_id}/close")
    async def close(session: Annotated[Session, Depends(owned)]) -> Closed:
        return Closed(finalized=await manager.close(session))

    @router.post("/sessions/{session_id}/interrupt")
    async def interrupt(
        session: Annotated[Session, Depends(owned)], body: Cancellation | None = None
    ) -> dict[str, str]:
        manager.interrupt(session, task_id=body.task_id if body else None)
        return {
            "delegation": session.portfolio.status
            if manager.settings.intent_cancellation
            else session.delegation.status
        }

    @router.post("/sessions/{session_id}/token")
    async def token(_session: Annotated[Session, Depends(owned)]) -> None:
        message = "GPT-Live uses /offer; ephemeral credentials are unsupported"
        raise UnsupportedCapability(message)

    return router
