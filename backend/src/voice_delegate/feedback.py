"""Bounded diagnostic categories only; never accept conversation content."""

import hashlib
import sqlite3
import time
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from voice_delegate.session.models import SessionError


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagnostic_id: UUID
    category: Literal["wrong_answer", "source", "audio", "connection", "other"]
    state: Literal["ready", "connecting", "connected", "working", "busy", "recovering", "ended"]


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
            "category TEXT, state TEXT, provider TEXT, version TEXT, created REAL)"
        )
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
            "SELECT principal, category, state FROM feedback WHERE id=?", (report_id,)
        ).fetchone()
        if row:
            if row[0] != identity:
                raise SessionError(404, "Diagnostic report unavailable")
            if row[1:] != (body.category, body.state):
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
                "INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?, ?)",
                (report_id, identity, body.category, body.state, provider, self.version, now),
            )
        self.db.commit()

    def close(self) -> None:
        self.db.close()
