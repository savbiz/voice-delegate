"""Bounded diagnostic categories and an optional short note the reporter typed.

The app never attaches audio or conversation text. The note holds only what the user writes;
it is stored with the report, never logged, and deleted with it after seven days.
"""

import hashlib
import re
import sqlite3
import time
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from voice_delegate.session.models import SessionError

LOOKS_LIKE_A_KEY = re.compile(r"[A-Za-z0-9_\-]{32,}")


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagnostic_id: UUID
    category: Literal["wrong_answer", "source", "audio", "connection", "other"]
    state: Literal["ready", "connecting", "connected", "working", "busy", "recovering", "ended"]
    adapter: Literal["openai", "azure", "elevenlabs"] | None = None
    note: str = Field(default="", max_length=500)

    @field_validator("note")
    @classmethod
    def plain_note(cls, value: str) -> str:
        note = " ".join(value.split())
        # A long unbroken token is almost certainly a pasted API key or invitation code.
        if LOOKS_LIKE_A_KEY.search(note):
            message = "The note looks like it contains a key or code; remove it"
            raise ValueError(message)
        return note


class FeedbackStore:
    """One immutable report per diagnostic ID, five reports per identity per day."""

    retention_seconds = 7 * 86400

    def __init__(self, path: str, capacity: int = 10000) -> None:
        self.version = version("voice-delegate")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=2)
        if path != ":memory:":
            Path(path).chmod(0o600)
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, principal TEXT, "
            "category TEXT, state TEXT, provider TEXT, version TEXT, created REAL, note TEXT)"
        )
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(feedback)")}
        if "note" not in columns:
            # Databases created before notes existed keep their reports.
            self.db.execute("ALTER TABLE feedback ADD COLUMN note TEXT")
        self.db.commit()
        self.capacity = capacity
        self.purge()

    def purge(self) -> None:
        with self.db:
            self.db.execute(
                "DELETE FROM feedback WHERE created <= ?", (time.time() - self.retention_seconds,)
            )

    def submit(self, principal: str, body: FeedbackInput, provider: str) -> str:
        identity = hashlib.sha256(principal.encode()).hexdigest()
        report_id = str(body.diagnostic_id)
        now = time.time()
        try:
            self._store(identity, report_id, now, body, provider)
        except SessionError:
            self.db.rollback()
            raise
        except sqlite3.Error as exc:
            self.db.rollback()
            raise SessionError(503, "Feedback temporarily unavailable") from exc

        return report_id

    def _store(
        self, identity: str, report_id: str, now: float, body: FeedbackInput, provider: str
    ) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute("DELETE FROM feedback WHERE created <= ?", (now - self.retention_seconds,))
        row = self.db.execute(
            "SELECT principal, category, state, COALESCE(note, '') FROM feedback WHERE id=?",
            (report_id,),
        ).fetchone()
        if row:
            if row[0] != identity:
                raise SessionError(404, "Diagnostic report unavailable")
            if row[1:] != (body.category, body.state, body.note):
                raise SessionError(409, "This diagnostic report has already been submitted")
        else:
            count = self.db.execute(
                "SELECT COUNT(*) FROM feedback WHERE principal=? AND created>=?",
                (identity, now - 86400),
            ).fetchone()[0]
            if count >= 5:
                raise SessionError(429, "Feedback limit reached; try again tomorrow")
            if self.db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] >= self.capacity:
                raise SessionError(503, "Feedback temporarily unavailable")
            self.db.execute(
                "INSERT INTO feedback (id, principal, category, state, provider, version, created, "
                "note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    report_id,
                    identity,
                    body.category,
                    body.state,
                    provider,
                    self.version,
                    now,
                    body.note or None,
                ),
            )
        self.db.commit()

    def close(self) -> None:
        self.db.close()
