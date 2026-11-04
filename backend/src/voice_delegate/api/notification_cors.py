"""Let the ntfy web app read the result of an Approve or Deny notification button."""

from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ACCESS_PREFIX = "/access/"


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class NotificationActionCors:
    """Allow the notification origin to read `/access/` responses, and nothing else.

    The ntfy web app sends the button as a simple cross-origin POST, so there is no preflight.
    Without this header the browser hides the response even when the decision succeeded: ntfy
    then reports a failed fetch and keeps the buttons instead of clearing the notification.
    The one-time secret in the path stays the credential; this only exposes the result.
    """

    def __init__(self, app: ASGIApp, origin: str) -> None:
        self.app = app
        self.origin = origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not scope["path"].startswith(ACCESS_PREFIX)
            or Headers(scope=scope).get("origin") != self.origin
        ):
            await self.app(scope, receive, send)
            return

        async def send_with_origin(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Access-Control-Allow-Origin"] = self.origin
                headers.add_vary_header("Origin")
            await send(message)

        await self.app(scope, receive, send_with_origin)
