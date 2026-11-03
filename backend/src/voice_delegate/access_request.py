"""Let a visitor ask the owner for an invitation; the owner is notified through ntfy.

Nothing is stored. The request is forwarded once to an operator-configured HTTPS topic URL.
A single-process budget bounds how often the owner can be notified, so a public endpoint
cannot become a spam channel.
"""

import time
from collections import deque
from collections.abc import Callable

import httpx
from pydantic import BaseModel, ConfigDict, Field

from voice_delegate.session.models import SessionError


class AccessRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contact: str = Field(min_length=3, max_length=120)
    note: str = Field(default="", max_length=300)


class AccessRequests:
    """Forward at most `limit` requests per `window` seconds, and one per contact per window."""

    def __init__(
        self,
        url: str,
        client: httpx.AsyncClient | None = None,
        limit: int = 5,
        window: float = 3600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url
        self.client = client or httpx.AsyncClient(timeout=5, follow_redirects=False)
        self.limit = limit
        self.window = window
        self.clock = clock
        self.sent: deque[tuple[float, str]] = deque()

    async def submit(self, body: AccessRequestInput) -> None:
        now = self.clock()
        while self.sent and self.sent[0][0] <= now - self.window:
            self.sent.popleft()
        contact = " ".join(body.contact.split()).casefold()
        if any(sent == contact for _, sent in self.sent):
            return
        if len(self.sent) >= self.limit:
            raise SessionError(429, "Too many access requests; please try again later")
        message = f"Contact: {' '.join(body.contact.split())}"
        if body.note.strip():
            message += f"\nNote: {' '.join(body.note.split())}"
        try:
            response = await self.client.post(
                self.url,
                content=message.encode(),
                headers={"Title": "voice-delegate access request", "Tags": "key"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SessionError(503, "Access requests are temporarily unavailable") from exc
        self.sent.append((now, contact))

    async def aclose(self) -> None:
        await self.client.aclose()
