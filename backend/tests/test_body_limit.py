"""Exercise streaming ASGI bodies without HTTP client buffering."""

import pytest
from starlette.types import Message, Receive, Scope, Send
from voice_delegate.limits.http import BodyLimitMiddleware


@pytest.mark.parametrize(("limit", "expected"), [(6, 200), (5, 413)])
async def test_chunked_body_is_bounded_and_replayed_once(limit: int, expected: int) -> None:
    incoming: list[Message] = [
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"def", "more_body": False},
        {"type": "http.disconnect"},
    ]
    sent: list[Message] = []
    received: list[Message] = []

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        received.extend([await receive(), await receive()])
        await send({"type": "http.response.start", "status": 200})

    await BodyLimitMiddleware(app, limit)({"type": "http"}, receive, send)
    assert sent[0]["status"] == expected
    if expected == 200:
        assert received == [
            {"type": "http.request", "body": b"abcdef", "more_body": False},
            {"type": "http.disconnect"},
        ]
    else:
        assert received == []


async def test_disconnect_mid_body_does_not_invoke_app() -> None:
    incoming: list[Message] = [
        {"type": "http.request", "body": b"partial", "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        pytest.fail("Disconnected request must not emit a response")

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        pytest.fail("Partial request must not reach the application")

    await BodyLimitMiddleware(app, 100)({"type": "http"}, receive, send)


async def test_non_http_scope_passes_through_untouched() -> None:
    received: list[Scope] = []
    scope: Scope = {"type": "lifespan"}

    async def receive() -> Message:
        pytest.fail("Middleware must not consume non-HTTP messages")

    async def send(message: Message) -> None:
        pytest.fail("Middleware must not emit non-HTTP messages")

    async def app(actual: Scope, incoming: Receive, outgoing: Send) -> None:
        received.append(actual)
        assert incoming is receive and outgoing is send

    await BodyLimitMiddleware(app, 1)(scope, receive, send)
    assert received == [scope]
