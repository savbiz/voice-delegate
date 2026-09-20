"""Local-demo HTTP routes with per-session ownership and origin validation."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from voice_delegate.providers.models import UnsupportedCapability
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import Session

from .schemas import Answer, Closed, Created, Offer, Status


def build_router(manager: SessionManager) -> APIRouter:
    """Bind a router to one lifecycle-owned manager, avoiding untyped app state."""

    async def check_origin(request: Request, response: Response) -> None:
        if request.headers.get("origin") != manager.settings.allowed_origin:
            raise HTTPException(403, "Unexpected request origin")
        response.headers["Cache-Control"] = "no-store"

    router = APIRouter(prefix="/api", dependencies=[Depends(check_origin)])

    async def owned(session_id: str, x_session_key: Annotated[str, Header()] = "") -> Session:
        return manager.get(session_id, x_session_key)

    @router.post("/sessions", status_code=201)
    async def create() -> Created:
        session = manager.create()
        return Created(
            id=session.id, key=session.key, ttl_seconds=manager.settings.session_ttl_seconds
        )

    @router.post("/sessions/{session_id}/offer")
    async def offer(body: Offer, session: Annotated[Session, Depends(owned)]) -> Answer:
        result = await manager.connect(session, body.sdp)
        return Answer(sdp=result.sdp)

    @router.post("/sessions/{session_id}/heartbeat")
    async def heartbeat(session: Annotated[Session, Depends(owned)]) -> Status:
        manager.heartbeat(session)
        return Status(state=session.state)

    @router.post("/sessions/{session_id}/close")
    async def close(session: Annotated[Session, Depends(owned)]) -> Closed:
        return Closed(finalized=await manager.close(session))

    @router.post("/sessions/{session_id}/token")
    async def token(session: Annotated[Session, Depends(owned)]) -> None:
        raise UnsupportedCapability("GPT-Live uses /offer; ephemeral credentials are unsupported")

    return router
