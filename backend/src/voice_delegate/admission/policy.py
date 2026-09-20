"""Fail-closed invite authentication and daily capacity reservations, without secrets on disk."""

import hashlib
import logging
import math
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from secrets import compare_digest

from voice_delegate.config import Settings
from voice_delegate.session.models import SessionError


class Admission:
    """Persist conservative full-session reservations; never refund ambiguous provider usage."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database: sqlite3.Connection | None = None
        if settings.public_demo:
            Path(settings.quota_database).parent.mkdir(parents=True, exist_ok=True)
            self.database = sqlite3.connect(settings.quota_database, timeout=2)
            self.database.execute("PRAGMA journal_mode=WAL")
            self.database.execute(
                "CREATE TABLE IF NOT EXISTS reservations "
                "(day TEXT, principal TEXT, sessions INTEGER, seconds INTEGER, "
                "PRIMARY KEY(day, principal))"
            )
            self.database.execute(
                "CREATE TABLE IF NOT EXISTS leases "
                "(session_id TEXT PRIMARY KEY, principal TEXT, expires REAL)"
            )
            self.database.commit()

    def authenticate(self, authorization: str) -> str:
        actual = (
            authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        )
        if self.settings.invite_tokens:
            identity = None
            for user, token in self.settings.invite_tokens.items():
                if compare_digest(actual.encode(), token.get_secret_value().encode()):
                    identity = user
            if identity is None:
                raise SessionError(401, "A valid personal invitation is required")
            return identity
        expected = self.settings.access_token.get_secret_value()
        if expected and not compare_digest(actual.encode(), expected.encode()):
            raise SessionError(401, "A valid demo access code is required")
        return "local"

    def reserve(self, principal: str, session_id: str) -> None:
        if not self.settings.demo_enabled:
            raise SessionError(503, "New conversations are temporarily disabled")
        database = self.database
        if database is None:
            return
        day = datetime.now(UTC).date().isoformat()
        identity = hashlib.sha256(principal.encode()).hexdigest()
        # Reserve both providers for a whole TTL, including one-second janitor granularity.
        seconds = math.ceil(self.settings.session_ttl_seconds + 1) * (
            2 if self.settings.fallback_enabled else 1
        )
        try:
            database.execute("BEGIN IMMEDIATE")
            database.execute("DELETE FROM reservations WHERE day < ?", (day,))
            now = time.time()
            database.execute("DELETE FROM leases WHERE expires <= ?", (now,))
            active = database.execute("SELECT COUNT(*) FROM leases").fetchone()[0]
            personal = database.execute(
                "SELECT COUNT(*) FROM leases WHERE principal=?", (identity,)
            ).fetchone()[0]
            if (
                active >= self.settings.max_sessions
                or personal >= self.settings.concurrent_sessions_per_user
            ):
                raise SessionError(429, "Shared session capacity reached")
            row = database.execute(
                "SELECT sessions, seconds FROM reservations WHERE day=? AND principal=?",
                (day, identity),
            ).fetchone()
            sessions, used = row or (0, 0)
            total = database.execute(
                "SELECT COALESCE(SUM(seconds), 0) FROM reservations WHERE day=?", (day,)
            ).fetchone()[0]
            if (
                sessions >= self.settings.daily_sessions_per_user
                or used + seconds > self.settings.daily_voice_seconds_per_user
                or total + seconds > self.settings.daily_voice_seconds_global
            ):
                raise SessionError(429, "Daily demo allowance exhausted; try again tomorrow (UTC)")
            database.execute(
                "INSERT INTO reservations VALUES (?, ?, 1, ?) ON CONFLICT(day, principal) "
                "DO UPDATE SET sessions=sessions+1, seconds=seconds+excluded.seconds",
                (day, identity, seconds),
            )
            database.execute(
                "INSERT INTO leases VALUES (?, ?, ?)",
                (
                    session_id,
                    identity,
                    now
                    + self.settings.session_ttl_seconds
                    + self.settings.connect_timeout_seconds
                    + self.settings.close_timeout_seconds
                    + 3,
                ),
            )
            database.commit()
        except SessionError:
            database.rollback()
            raise
        except sqlite3.Error as exc:
            database.rollback()
            raise SessionError(503, "Demo allowance store unavailable") from exc

    def release(self, session_id: str) -> None:
        if self.database is not None:
            try:
                self.database.execute("DELETE FROM leases WHERE session_id=?", (session_id,))
                self.database.commit()
            except sqlite3.Error:
                # Retain admission conservatively; the lease expires after its fixed lifetime.
                self.database.rollback()
                logging.getLogger(__name__).warning("Lease release unavailable; awaiting expiry")

    def close(self) -> None:
        if self.database is not None:
            self.database.close()
