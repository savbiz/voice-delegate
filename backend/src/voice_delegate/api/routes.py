"""Local-demo HTTP routes with per-session ownership and origin validation."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from voice_delegate_agent.reference import search, source_by_id

from voice_delegate.feedback import FeedbackInput, FeedbackStore
from voice_delegate.providers.models import UnsupportedCapability
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import Session
from voice_delegate.session.preferences import VoicePreferences

from .schemas import Answer, Closed, Created, Offer, Reconnect, Status


class ReferenceQuery(BaseModel):
    query: str = Field(min_length=1, max_length=500)


def build_router(manager: SessionManager, feedback: FeedbackStore | None = None) -> APIRouter:
    """Bind a router to one lifecycle-owned manager, avoiding untyped app state."""

    async def check_origin(request: Request, response: Response) -> None:
        if request.headers.get("origin") != manager.settings.allowed_origin:
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
            delegation=session.delegation.status,
            generation=session.generation,
            sources=session.delegation.sources,
            recap=session.recap,
            fallback_available=manager.fallback is not None and not session.fallback_used,
        )

    @router.post("/sessions/{session_id}/close")
    async def close(session: Annotated[Session, Depends(owned)]) -> Closed:
        return Closed(finalized=await manager.close(session))

    @router.post("/sessions/{session_id}/interrupt")
    async def interrupt(session: Annotated[Session, Depends(owned)]) -> dict[str, str]:
        manager.interrupt(session)
        return {"delegation": session.delegation.status}

    @router.post("/sessions/{session_id}/token")
    async def token(session: Annotated[Session, Depends(owned)]) -> None:
        raise UnsupportedCapability("GPT-Live uses /offer; ephemeral credentials are unsupported")

    return router
