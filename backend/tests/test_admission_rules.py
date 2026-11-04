"""Authentication and admission edge cases that the happy-path and property tests do not pin down.

Each assertion names a rule that, if broken, would admit someone who should be refused (or refuse
someone who should be admitted). Mutation testing (docs/testing.md) found them unprotected.
"""

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from conftest import PublicSettingsFactory
from voice_delegate.admission.policy import Admission
from voice_delegate.config import Settings
from voice_delegate.session.models import SessionError

CODE = "c" * 32
PERSONAL = "A valid personal invitation is required"
DEMO = "A valid demo access code is required"


def refused(admission: Admission, header: str) -> SessionError:
    with pytest.raises(SessionError) as caught:
        admission.authenticate(header)
    return caught.value


def test_open_local_development_accepts_any_header() -> None:
    admission = Admission(Settings())
    assert admission.authenticate("") == "local"
    assert admission.authenticate("Bearer anything") == "local"
    assert admission.invites is None


def test_demo_access_code_must_be_sent_as_a_bearer_token() -> None:
    admission = Admission(Settings.model_validate({"access_token": CODE}))
    assert admission.authenticate("Bearer " + CODE) == "local"
    for header in ("", "Bearer", "Bearer ", "Bearer wrong", CODE, "bearer " + CODE):
        error = refused(admission, header)
        assert (error.status, str(error)) == (401, DEMO), header


def test_configured_invitations_identify_their_owner_and_nobody_else() -> None:
    admission = Admission(
        Settings.model_validate({"invite_tokens": {"alice": "a" * 32, "bob": "b" * 32}})
    )
    assert admission.authenticate("Bearer " + "a" * 32) == "alice"
    assert admission.authenticate("Bearer " + "b" * 32) == "bob"
    for header in ("", "Bearer nope", "a" * 32):
        error = refused(admission, header)
        assert (error.status, str(error)) == (401, PERSONAL), header


def test_database_invitations_authenticate_and_never_fall_back_to_the_open_identity(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    admission = Admission(public_settings(tmp_path, invite_tokens={}))
    assert admission.invites is not None
    admission.invites.add("friend", CODE)
    assert admission.authenticate("Bearer " + CODE) == "friend"
    for header in ("", "Bearer " + "d" * 32, CODE):
        error = refused(admission, header)
        assert (error.status, str(error)) == (401, PERSONAL), header
    admission.invites.revoke("friend")
    assert refused(admission, "Bearer " + CODE).status == 401
    admission.close()


def test_a_database_invitation_wins_over_the_configured_ones(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    admission = Admission(public_settings(tmp_path))
    assert admission.invites is not None
    admission.invites.add("db-user", CODE)
    assert admission.authenticate("Bearer " + CODE) == "db-user"
    assert admission.authenticate("Bearer " + "a" * 32) == "alice"
    admission.close()


def test_the_invitation_store_exists_for_a_public_demo_or_a_public_api_only(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    public = Admission(public_settings(tmp_path))
    assert public.invites is not None
    public.close()
    api_only = Admission(
        Settings(
            public_api_url="https://api.example.com",
            access_request_url="https://ntfy.example/a-long-topic-name",
            access_database=str(tmp_path / "i.db"),
        )
    )
    assert api_only.invites is not None
    api_only.close()
    assert Admission(Settings()).invites is None


def test_the_quota_database_directory_is_created_and_reused(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    nested = tmp_path / "deep" / "er" / "quotas.sqlite3"
    settings = public_settings(tmp_path, quota_database=str(nested))
    first = Admission(settings)
    first.close()
    second = Admission(settings)  # the directory already exists
    assert nested.exists()
    second.close()


def test_disabled_demo_refuses_new_sessions_with_a_clear_message(tmp_path: Path) -> None:
    admission = Admission(Settings(demo_enabled=False))
    with pytest.raises(SessionError) as caught:
        admission.reserve("alice", "s1")
    assert (caught.value.status, str(caught.value)) == (
        503,
        "New conversations are temporarily disabled",
    )


class BrokenStore:
    """A quota store whose every statement fails, as on a full or read-only disk."""

    rolled_back = False

    def execute(self, *_: Any) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    def rollback(self) -> None:
        self.rolled_back = True


def test_a_failing_quota_store_fails_closed_with_a_message_and_a_rollback(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    admission = Admission(public_settings(tmp_path))
    real = admission.database
    broken = BrokenStore()
    admission.database = broken  # type: ignore[assignment]
    with pytest.raises(SessionError) as caught:
        admission.reserve("alice", "s1", recovery=False)
    assert (caught.value.status, str(caught.value)) == (503, "Demo allowance store unavailable")
    assert broken.rolled_back
    admission.database = real
    admission.close()


def test_a_personal_lease_is_stored_under_its_session_and_can_be_released(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    admission = Admission(public_settings(tmp_path))
    admission.reserve_personal("alice", "personal-1")
    database = admission.database
    assert database is not None
    assert database.execute("SELECT session_id, personal FROM leases").fetchall() == [
        ("personal-1", 1)
    ]
    admission.release("personal-1")
    assert database.execute("SELECT COUNT(*) FROM leases").fetchone() == (0,)
    admission.close()


def test_azure_recovery_reserves_twice_the_voice_seconds(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    admission = Admission(public_settings(tmp_path, daily_voice_seconds_per_user=100))
    database = admission.database
    assert database is not None
    admission.reserve("alice", "plain", recovery=False)
    admission.release("plain")
    admission.reserve("alice", "azure", recovery=True)
    # ttl 10 s + 1 = 11 s per provider; the recovery session reserves both providers.
    assert database.execute("SELECT sessions, seconds FROM reservations").fetchone() == (2, 33)
    admission.release("azure")
    admission.close()


def test_an_unspecified_recovery_follows_the_server_setting(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    admission = Admission(public_settings(tmp_path))
    database = admission.database
    assert database is not None
    admission.reserve("alice", "default")
    assert database.execute("SELECT seconds FROM reservations").fetchone() == (11,)
    admission.close()
