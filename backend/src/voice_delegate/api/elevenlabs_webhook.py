"""Authenticated server-tool ingress; deliberately separate from browser Origin policy."""

import asyncio
from collections.abc import Callable, Coroutine
from secrets import compare_digest
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

from voice_delegate.providers.elevenlabs_session import ElevenLabsConnection
from voice_delegate.providers.models import ProviderError
from voice_delegate.session.manager import SessionManager

WEBHOOK_TIMEOUT_SECONDS = 115


class ServiceRoute(APIRoute):
    """Never echo invalid tool text and never cache service responses, including errors."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                response = await handler(request)
            except RequestValidationError:
                response = JSONResponse({"detail": "Invalid webhook request"}, status_code=422)
            except HTTPException as error:
                response = JSONResponse({"detail": error.detail}, status_code=error.status_code)
            response.headers["Cache-Control"] = "no-store"
            return response

        return handle


class WebhookInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, max_length=8192)

    @field_validator("goal")
    @classmethod
    def bounded_goal(cls, goal: str) -> str:
        goal = goal.strip()
        if not goal or len(goal.encode()) > 8192:
            message = "A bounded delegation goal is required"
            raise ValueError(message)
        return goal


def build_webhook_router(manager: SessionManager) -> APIRouter:
    router = APIRouter(route_class=ServiceRoute)

    async def authenticated(
        request: Request,
        x_voice_webhook_token: Annotated[str, Header()] = "",
        x_voice_conversation_id: Annotated[str, Header()] = "",
    ) -> None:
        matching = next(
            (
                s
                for s in manager.sessions.values()
                if isinstance(s.connection, ElevenLabsConnection)
                and s.connection.conversation_id == x_voice_conversation_id
            ),
            None,
        )
        owner = manager.owner_for(matching) if matching is not None else manager
        expected = owner.settings.elevenlabs_webhook_token.get_secret_value()
        if len(expected) < 32 or not compare_digest(
            expected.encode(), x_voice_webhook_token.encode()
        ):
            raise HTTPException(401, "Webhook authentication required")
        if request.headers.get("origin") is not None:
            raise HTTPException(403, "Browser requests are not accepted on service ingress")

    @router.post("/integrations/elevenlabs/delegate", dependencies=[Depends(authenticated)])
    async def delegate(
        body: WebhookInput,
        request: Request,
        response: Response,
        x_voice_conversation_id: Annotated[str, Header()] = "",
    ) -> dict[str, str]:
        response.headers["Cache-Control"] = "no-store"
        if not 1 <= len(x_voice_conversation_id) <= 200:
            raise HTTPException(404, "Conversation unavailable")
        session = next(
            (
                s
                for s in manager.sessions.values()
                if isinstance(s.connection, ElevenLabsConnection)
                and s.connection.conversation_id == x_voice_conversation_id
            ),
            None,
        )
        if session is None or session.state not in {"connecting", "connected"}:
            raise HTTPException(404, "Conversation unavailable")
        owner = manager.owner_for(session)
        now = owner.clock()
        if (
            now - session.created_at >= owner.settings.session_ttl_seconds
            or now - session.last_heartbeat >= owner.settings.heartbeat_timeout_seconds
        ):
            raise HTTPException(404, "Conversation unavailable")
        connection = session.connection
        assert isinstance(connection, ElevenLabsConnection)
        if connection.closed:
            raise HTTPException(404, "Conversation unavailable")
        if not connection.started:
            connection.start()
            owner.attach_sdk(session, connection)
        if sum(c.waiters for c in connection.calls.values()) >= 8:
            raise HTTPException(429, "Webhook waiter capacity reached")
        try:
            identity, call = connection.admit(body.goal)
        except ProviderError as error:
            raise HTTPException(429, "Webhook call capacity reached") from error
        if call.waiters >= 4:
            raise HTTPException(429, "Webhook waiter capacity reached")
        loop = asyncio.get_running_loop()
        if not call.deadline:
            call.deadline = loop.time() + WEBHOOK_TIMEOUT_SECONDS
        call.waiters += 1
        try:
            while not call.ready.is_set():
                remaining = call.deadline - loop.time()
                if remaining <= 0:
                    connection.settle(identity, "Tool response window expired; task incomplete.")
                    break
                if await request.is_disconnected():
                    # An interrupted HTTP waiter is not user cancellation. The bounded worker
                    # continues; a repeated goal can collect the cached response without replay.
                    raise HTTPException(499, "Webhook request disconnected")
                try:
                    await asyncio.wait_for(call.ready.wait(), timeout=min(0.1, remaining))
                except TimeoutError:
                    continue
            return {"result": call.result or "Task ended without a deliverable result."}
        finally:
            call.waiters -= 1

    return router
