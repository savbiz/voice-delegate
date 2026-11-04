"""Let a visitor ask the owner for an invitation, and optionally approve it remotely.

Notification only (``VOICE_ACCESS_REQUEST_URL``): the request is forwarded once to an ntfy
topic and nothing is stored.

Remote approval (also ``VOICE_PUBLIC_API_URL``): the visitor gives an email address, the
ntfy notification carries Approve and Deny buttons bound to a one-time secret, and approval
sends the owner a second notification with the new code and a prefilled email to forward.
The email address is kept only until the owner decides or the request expires; afterwards
only its hash remains, to refuse repeated requests for a cooling-off period.
Invitation codes are stored only as SHA-256 hashes.
"""

import hashlib
import re
import secrets
import sqlite3
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

from voice_delegate.session.models import SessionError

REQUEST_TTL_SECONDS = 7 * 86400
COOLDOWN_SECONDS = 30 * 86400
DAILY_REQUESTS = 20
EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$"


class AccessRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contact: str = Field(min_length=3, max_length=120)
    note: str = Field(default="", max_length=300)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalize(value: str) -> str:
    return " ".join(value.split())


class InviteStore:
    """Pending requests and approved invitations in one SQLite file."""

    def __init__(self, path: str, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # SQLite calls are synchronous by design for the single-process demo.
        self.db = sqlite3.connect(path, timeout=2)
        if path != ":memory:":
            Path(path).chmod(0o600)
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, email TEXT, "
            "email_hash TEXT NOT NULL, note TEXT, secret_hash TEXT NOT NULL, "
            "created REAL NOT NULL, status TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS invites (principal TEXT PRIMARY KEY, "
            "token_hash TEXT NOT NULL UNIQUE, created REAL NOT NULL)"
        )
        self.db.commit()
        self.purge()

    def purge(self) -> None:
        now = self.clock()
        with self.db:
            # Expired pending requests lose their address but keep the cooling-off hash.
            self.db.execute(
                "UPDATE requests SET email=NULL, note=NULL, status='expired' "
                "WHERE status='pending' AND created <= ?",
                (now - REQUEST_TTL_SECONDS,),
            )
            self.db.execute(
                "DELETE FROM requests WHERE status!='approved' AND created <= ?",
                (now - COOLDOWN_SECONDS,),
            )

    def open(self, email: str, note: str) -> tuple[str, str] | None:
        """Return (id, secret) for a new request, or None when it must be ignored."""
        self.purge()
        now = self.clock()
        email_hash = digest(email)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            recent = self.db.execute(
                "SELECT 1 FROM requests WHERE email_hash=? AND (status='approved' OR created > ?)",
                (email_hash, now - COOLDOWN_SECONDS),
            ).fetchone()
            if recent:
                return None
            today = self.db.execute(
                "SELECT COUNT(*) FROM requests WHERE created > ?", (now - 86400,)
            ).fetchone()[0]
            if today >= DAILY_REQUESTS:
                raise SessionError(429, "Too many access requests; please try again later")
            request_id = secrets.token_urlsafe(12)
            secret = secrets.token_urlsafe(32)
            self.db.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                (request_id, email, email_hash, note, digest(secret), now),
            )
        return request_id, secret

    def withdraw(self, request_id: str) -> None:
        """Forget a request whose owner notification could not be delivered."""
        with self.db:
            self.db.execute("DELETE FROM requests WHERE id=?", (request_id,))

    def pending(self, request_id: str, secret: str) -> str:
        """Return the address of an open request after checking its one-time secret."""
        self.purge()
        row = self.db.execute(
            "SELECT email, secret_hash, status FROM requests WHERE id=?", (request_id,)
        ).fetchone()
        if row is None or not secrets.compare_digest(row[1], digest(secret)):
            raise SessionError(404, "Access request not found")
        if row[2] != "pending" or row[0] is None:
            raise SessionError(409, "This access request was already decided or has expired")
        return str(row[0])

    def approve(self, request_id: str, secret: str) -> tuple[str, str]:
        """Create an invitation; returns (email, token). The caller must send or revoke it."""
        email = self.pending(request_id, secret)
        token = secrets.token_urlsafe(32)
        principal = "email-" + digest(email)[:16]
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO invites VALUES (?, ?, ?)",
                (principal, digest(token), self.clock()),
            )
        return email, token

    def revoke_token(self, token: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM invites WHERE token_hash=?", (digest(token),))

    def decide(self, request_id: str, status: Literal["approved", "denied"]) -> None:
        with self.db:
            self.db.execute(
                "UPDATE requests SET email=NULL, note=NULL, status=? WHERE id=?",
                (status, request_id),
            )

    def deny(self, request_id: str, secret: str) -> None:
        self.pending(request_id, secret)
        self.decide(request_id, "denied")

    def principal(self, token: str) -> str | None:
        """Map an invitation code to its pseudonymous principal, if one was approved."""
        if not token:
            return None
        row = self.db.execute(
            "SELECT principal FROM invites WHERE token_hash=?", (digest(token),)
        ).fetchone()
        return str(row[0]) if row else None

    def add(self, name: str, token: str) -> None:
        """Store a named invitation; raises if the name exists (revoke it first to rotate)."""
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO invites VALUES (?, ?, ?)", (name, digest(token), self.clock())
                )
        except sqlite3.IntegrityError as exc:
            message = f"Invitation {name!r} already exists"
            raise ValueError(message) from exc

    def revoke(self, name: str) -> bool:
        with self.db:
            return self.db.execute("DELETE FROM invites WHERE principal=?", (name,)).rowcount > 0

    def names(self) -> list[tuple[str, float]]:
        return [
            (str(name), float(created))
            for name, created in self.db.execute(
                "SELECT principal, created FROM invites ORDER BY created"
            )
        ]

    def close(self) -> None:
        self.db.close()


class Approval(BaseModel):
    """Settings for remote approval; all fields are operator configuration."""

    public_api_url: str
    frontend_url: str


class AccessRequests:
    """Forward at most `limit` requests per `window` seconds, and one per contact per window."""

    def __init__(
        self,
        url: str,
        client: httpx.AsyncClient | None = None,
        limit: int = 5,
        window: float = 3600,
        clock: Callable[[], float] = time.monotonic,
        store: InviteStore | None = None,
        approval: Approval | None = None,
    ) -> None:
        if (store is None) != (approval is None):
            message = "Remote approval needs both an invite store and approval settings"
            raise ValueError(message)
        self.url = url
        self.client = client or httpx.AsyncClient(timeout=5, follow_redirects=False)
        self.limit = limit
        self.window = window
        self.clock = clock
        self.store = store
        self.approval = approval
        self.sent: deque[tuple[float, str]] = deque()

    @property
    def requires_email(self) -> bool:
        return self.approval is not None

    async def submit(self, body: AccessRequestInput) -> None:
        now = self.clock()
        while self.sent and self.sent[0][0] <= now - self.window:
            self.sent.popleft()
        contact = normalize(body.contact)
        key = contact.casefold()
        if self.approval is not None and not re.fullmatch(EMAIL_PATTERN, contact):
            raise SessionError(422, "Enter a valid email address")
        if any(sent == key for _, sent in self.sent):
            return
        if len(self.sent) >= self.limit:
            raise SessionError(429, "Too many access requests; please try again later")
        message = f"Contact: {contact}"
        if body.note.strip():
            message += f"\nNote: {normalize(body.note)}"
        headers = {"Title": "voice-delegate access request", "Tags": "key"}
        opened: tuple[str, str] | None = None
        if self.store is not None and self.approval is not None:
            opened = self.store.open(key, normalize(body.note))
            if opened is None:
                # Same answer as a new request, so the endpoint does not reveal known addresses.
                return
            base = f"{self.approval.public_api_url}/access/{opened[0]}/{opened[1]}"
            headers["Actions"] = (
                f"http, Approve, {base}/approve, method=POST, clear=true; "
                f"http, Deny, {base}/deny, method=POST, clear=true"
            )
            message += "\nApprove creates a code and a prefilled email for you to send."
        try:
            response = await self.client.post(self.url, content=message.encode(), headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            if opened is not None and self.store is not None:
                self.store.withdraw(opened[0])
            raise SessionError(503, "Access requests are temporarily unavailable") from exc
        self.sent.append((now, key))

    async def approve(self, request_id: str, secret: str) -> None:
        if self.store is None or self.approval is None:
            raise SessionError(404, "Access request not found")
        email, token = self.store.approve(request_id, secret)
        subject = "Your voice-delegate invitation"
        text = (
            "Hello,\n\nyour request to try voice-delegate was approved.\n\n"
            f"Invitation code: {token}\n\n"
            f"Open {self.approval.frontend_url}, choose Platform API and paste the code. "
            "Keep it private: it is personal and daily limits apply.\n"
        )
        mailto = (
            f"mailto:{quote(email, safe='@')}"
            f"?subject={quote(subject, safe='')}&body={quote(text, safe='')}"
        )
        # The ntfy web app opens view actions in the browser (Safari on iPhone), where mailto
        # does not reach Gmail; Gmail's compose page opens prefilled in any browser.
        gmail = (
            "https://mail.google.com/mail/?view=cm&fs=1"
            f"&to={quote(email, safe='@')}&su={quote(subject, safe='')}&body={quote(text, safe='')}"
        )
        try:
            # Cache: no keeps the code off the ntfy server once delivered to the owner's phone.
            response = await self.client.post(
                self.url,
                content=f"Invitation code for {email}:\n{token}".encode(),
                headers={
                    "Title": "voice-delegate invitation approved",
                    "Tags": "white_check_mark",
                    "Cache": "no",
                    "Actions": (
                        f"view, Gmail, {gmail}, clear=true; view, Mail app, {mailto}, clear=true"
                    ),
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # An undelivered code is revoked; the request stays pending so Approve can be retried.
            self.store.revoke_token(token)
            raise SessionError(502, "The invitation code could not be delivered") from exc
        self.store.decide(request_id, "approved")

    def deny(self, request_id: str, secret: str) -> None:
        if self.store is None:
            raise SessionError(404, "Access request not found")
        self.store.deny(request_id, secret)

    async def aclose(self) -> None:
        await self.client.aclose()
        if self.store is not None:
            self.store.close()
