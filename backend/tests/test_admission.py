"""Public-demo admission must survive restarts and enforce identity before provider work."""

from pathlib import Path

import pytest
from conftest import ASGIClientFactory, PublicSettingsFactory
from pydantic import SecretStr
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import SessionError
from voice_delegate_agent.reference import WorkerResult


async def test_quotas_persist_across_restart_and_global_budget(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    settings = public_settings(tmp_path)
    manager = SessionManager(FakeProvider(), settings)
    first = manager.create("alice")
    with pytest.raises(SessionError) as concurrent:
        manager.create("alice")
    assert concurrent.value.status == 429
    await manager.close(first)
    await manager.aclose()
    manager = SessionManager(FakeProvider(), settings)
    await manager.close(manager.create("alice"))
    with pytest.raises(SessionError) as daily:
        manager.create("alice")
    assert daily.value.status == 429
    await manager.close(manager.create("bob"))
    with pytest.raises(SessionError):
        manager.create("bob")
    await manager.aclose()
    assert b"a" * 32 not in (tmp_path / "quotas.sqlite3").read_bytes()


async def test_personal_invitation_cannot_use_another_users_session(
    asgi_client: ASGIClientFactory, public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    app = create_app(public_settings(tmp_path), FakeProvider())
    async with asgi_client(app) as client:
        client.headers["Origin"] = "https://demo.example"
        assert (await client.post("/api/sessions")).status_code == 401
        client.headers["Authorization"] = "Bearer " + "a" * 32
        created = (await client.post("/api/sessions")).json()
        client.headers["X-Session-Key"] = created["key"]
        client.headers["Authorization"] = "Bearer " + "b" * 32
        path = f"/api/sessions/{created['id']}"
        assert (await client.post(path + "/close")).status_code == 404
        client.headers["Authorization"] = "Bearer " + "a" * 32
        assert (await client.post(path + "/close")).status_code == 200


async def test_kill_switch_prevents_admission_before_provider_work() -> None:
    provider = FakeProvider()
    manager = SessionManager(provider, Settings(demo_enabled=False))
    with pytest.raises(SessionError) as rejected:
        manager.create()
    assert rejected.value.status == 503
    assert not provider.connections
    await manager.aclose()


def test_public_configuration_rejects_shared_gate_and_duplicate_invites(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="named invitations"):
        public_settings(tmp_path, invite_tokens={})
    with pytest.raises(ValueError, match="unique random"):
        public_settings(
            tmp_path, invite_tokens={"alice": SecretStr("a" * 32), "bob": SecretStr("a" * 32)}
        )


def test_invalid_configuration_does_not_echo_invitation_secrets(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    sensitive = "private-token-for-validation-test-1234"
    with pytest.raises(ValueError) as error:
        public_settings(tmp_path, invite_tokens={"alice": sensitive, "bob": sensitive})
    assert sensitive not in str(error.value)


async def test_unwritable_budget_store_fails_closed(
    public_settings: PublicSettingsFactory, tmp_path: Path
) -> None:
    manager = SessionManager(FakeProvider(), public_settings(tmp_path))
    database = manager.admission.database
    assert database is not None
    database.execute("PRAGMA query_only=ON")
    with pytest.raises(SessionError) as rejected:
        manager.create("alice")
    assert rejected.value.status == 503
    assert not manager.sessions
    await manager.aclose()


async def test_delegation_allowance_prevents_additional_worker_calls() -> None:
    from voice_delegate.delegation.contracts import DelegationInput
    from voice_delegate.delegation.runner import DelegationRunner, DelegationState
    from voice_delegate.providers.fake import FakeConnection

    class Worker:
        calls = 0

        async def delegate_task(self, goal: str, context: str) -> WorkerResult:
            self.calls += 1
            return WorkerResult("done")

    worker = Worker()
    runner = DelegationRunner(worker, request_limit=1)
    state = DelegationState()
    connection = FakeConnection()
    runner.start(state, "first", DelegationInput(goal="task"), connection, lambda: True)
    assert state.task is not None
    await state.task
    runner.start(state, "second", DelegationInput(goal="task"), connection, lambda: True)
    assert state.status == "request_limit"
    assert worker.calls == 1
    await runner.aclose()


async def test_public_demo_environment_requires_invites_and_persists_quotas(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VOICE_ENVIRONMENT", "production")
    monkeypatch.setenv("VOICE_PUBLIC_DEMO", "true")
    monkeypatch.setenv("VOICE_ALLOWED_ORIGIN", "https://demo.example")
    monkeypatch.setenv("VOICE_QUOTA_DATABASE", str(tmp_path / "quotas.sqlite3"))
    monkeypatch.setenv("VOICE_FEEDBACK_DATABASE", str(tmp_path / "feedback.sqlite3"))
    monkeypatch.setenv("VOICE_INVITE_TOKENS", "{}")
    with pytest.raises(ValueError, match="named invitations"):
        Settings()
    monkeypatch.setenv("VOICE_INVITE_TOKENS", '{"alice":"' + "a" * 32 + '"}')
    manager = SessionManager(FakeProvider(), Settings())
    await manager.close(manager.create("alice"))
    await manager.aclose()
    manager = SessionManager(FakeProvider(), Settings())
    assert manager.admission.database is not None
    assert manager.admission.database.execute(
        "SELECT SUM(sessions) FROM reservations"
    ).fetchone() == (1,)
    await manager.aclose()
