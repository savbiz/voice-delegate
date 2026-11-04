"""Admission is checked against an independent reference model over random operation sequences.

Hypothesis explores interleavings of reservations, releases, lease expiry and day rollover that a
hand-written example would not. After every step the real SQLite-backed admission must agree
with a few lines of arithmetic written from the documented rules, and its counters must respect
every configured limit.
"""

import math
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)
from voice_delegate.admission.policy import Admission
from voice_delegate.config import Settings
from voice_delegate.session.models import SessionError

START = 1_700_000_000  # 2023-11-14 22:13 UTC, so a day rollover is a few steps away
PRINCIPALS = ["alice", "bob", "carol", "dave", "ops"]


# One reservation is 11 voice seconds. Each configuration makes a different limit the one that
# binds first, so a boundary error in any single limit cannot hide behind another.
CONFIGURATIONS = {
    "daily sessions bind": {"daily_sessions_per_user": 2, "daily_voice_seconds_per_user": 99},
    "user seconds bind": {"daily_sessions_per_user": 9, "daily_voice_seconds_per_user": 33},
    "global seconds bind": {
        "daily_sessions_per_user": 9,
        "daily_voice_seconds_per_user": 99,
        "daily_voice_seconds_global": 44,
    },
}


def make_settings(directory: Path, limits: dict[str, int]) -> Settings:
    return Settings.model_validate(
        {
            "environment": "production",
            "allowed_hosts": ["localhost"],
            "public_demo": True,
            "allowed_origins": ["https://demo.example"],
            "quota_database": str(directory / "quotas.sqlite3"),
            "access_database": str(directory / "access.sqlite3"),
            "invite_tokens": {name: name[0] * 32 for name in PRINCIPALS[:4]},
            "unlimited_invites": ["ops"],
            "session_ttl_seconds": 10,
            "max_sessions": 4,
            "concurrent_sessions_per_user": 2,
            "daily_voice_seconds_global": 66,
            **limits,
        }
    )


@dataclass
class Lease:
    principal: str
    expires: float
    personal: bool


class AdmissionMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.directory = tempfile.TemporaryDirectory()
        self.now = float(START)
        self.leases: dict[str, Lease] = {}
        self.days: dict[tuple[str, str], list[int]] = {}
        self.counter = 0

    def teardown(self) -> None:
        self.admission.close()
        self.directory.cleanup()

    @initialize(limits=st.sampled_from(sorted(CONFIGURATIONS)))
    def configure(self, limits: str) -> None:
        self.settings = make_settings(Path(self.directory.name), CONFIGURATIONS[limits])
        self.admission = Admission(self.settings, clock=lambda: self.now)
        # One reservation is the session lifetime plus one second, rounded up.
        self.seconds = math.ceil(self.settings.session_ttl_seconds + 1)
        self.lease_life = (
            self.settings.session_ttl_seconds
            + self.settings.connect_timeout_seconds
            + self.settings.close_timeout_seconds
            + 3
        )

    def today(self) -> str:
        return datetime.fromtimestamp(self.now, UTC).date().isoformat()

    def expire(self) -> None:
        self.leases = {k: v for k, v in self.leases.items() if v.expires > self.now}
        today = self.today()
        self.days = {k: v for k, v in self.days.items() if k[0] >= today}

    def expected_admission(self, principal: str, personal: bool) -> bool:
        """The documented rules, restated independently of the SQL."""
        self.expire()
        s = self.settings
        active = len(self.leases)
        if personal:
            personal_active = sum(lease.personal for lease in self.leases.values())
            if personal_active >= max(0, s.max_sessions - 1):
                return False
        mine = sum(lease.principal == principal for lease in self.leases.values())
        if active >= s.max_sessions or mine >= (1 if personal else s.concurrent_sessions_per_user):
            return False
        if not personal and principal not in s.unlimited_invites:
            sessions, used = self.days.get((self.today(), principal), [0, 0])
            total = sum(v[1] for k, v in self.days.items() if k[0] == self.today())
            if (
                sessions >= s.daily_sessions_per_user
                or used + self.seconds > s.daily_voice_seconds_per_user
                or total + self.seconds > s.daily_voice_seconds_global
            ):
                return False
        return True

    @rule(principal=st.sampled_from(PRINCIPALS), personal=st.booleans())
    def reserve(self, principal: str, personal: bool) -> None:
        # The model needs the principal hash only to mirror the store, so key on the raw name.
        expected = self.expected_admission(principal, personal)
        self.counter += 1
        session_id = f"s{self.counter}"
        refused: SessionError | None = None
        try:
            self.admission.reserve(principal, session_id, personal=personal, recovery=False)
        except SessionError as error:
            refused = error
        if refused is not None:
            assert refused.status == 429
            assert not expected, "admission refused a reservation the rules allow"
            return
        assert expected, "admission accepted a reservation the rules forbid"
        self.leases[session_id] = Lease(principal, self.now + self.lease_life, personal)
        if not personal and principal not in self.settings.unlimited_invites:
            entry = self.days.setdefault((self.today(), principal), [0, 0])
            entry[0] += 1
            entry[1] += self.seconds

    @precondition(lambda self: bool(self.leases))
    @rule(data=st.data())
    def release(self, data: st.DataObject) -> None:
        session_id = data.draw(st.sampled_from(sorted(self.leases)))
        self.admission.release(session_id)
        del self.leases[session_id]

    @rule(seconds=st.one_of(st.integers(0, 60), st.sampled_from([1800, 9000])))
    def advance(self, seconds: int) -> None:
        self.now += seconds

    @precondition(lambda self: bool(self.leases))
    @rule()
    def advance_to_next_expiry(self) -> None:
        """Land exactly on a lease's expiry instant, where an off-by-one would show."""
        self.now = max(self.now, min(lease.expires for lease in self.leases.values()))

    @invariant()
    def limits_hold_in_the_store(self) -> None:
        if not hasattr(self, "admission"):
            return
        database = self.admission.database
        assert isinstance(database, sqlite3.Connection)
        s = self.settings
        live = database.execute(
            "SELECT principal, COUNT(*) FROM leases WHERE expires > ? GROUP BY principal",
            (self.now,),
        ).fetchall()
        assert sum(count for _, count in live) <= s.max_sessions
        assert all(count <= s.concurrent_sessions_per_user for _, count in live)
        rows = database.execute("SELECT day, sessions, seconds FROM reservations").fetchall()
        per_day: dict[str, int] = {}
        for day, sessions, seconds in rows:
            assert sessions <= s.daily_sessions_per_user
            assert seconds <= s.daily_voice_seconds_per_user
            per_day[day] = per_day.get(day, 0) + seconds
        assert all(total <= s.daily_voice_seconds_global for total in per_day.values())


AdmissionMachine.TestCase.settings = settings(
    max_examples=150,
    stateful_step_count=40,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=list(HealthCheck),
)
TestAdmissionProperties = AdmissionMachine.TestCase
