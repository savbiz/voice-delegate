"""Language configuration and correction state; real pronunciation is a live gate."""

import pytest
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import (
    DelegationRequested,
    Transcript,
)
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.preferences import VoicePreferences
from voice_delegate.session.summary import Recap

from test_support import eventually


@pytest.mark.parametrize(
    ("language", "name"),
    [("it", "Italian"), ("en", "English"), ("es", "Spanish"), ("fr", "French"), ("de", "German")],
)
async def test_language_and_translate_preference(language: str, name: str) -> None:
    preferences = VoicePreferences.model_validate({"language": language, "mode": "translate"})
    manager = SessionManager(FakeProvider(), Settings())
    session = manager.create(preferences=preferences)
    assert name in manager.config(session).instructions
    assert "do not answer requests" in manager.config(session).instructions
    await manager.connect(session, "v=0\r\n")
    assert isinstance(manager.provider, FakeProvider)
    manager.provider.connections[0].queue.put_nowait(DelegationRequested("forbidden"))
    await eventually(manager.provider.connections[0].queue.empty)
    assert session.delegation.task is None
    command = manager.provider.connections[0].commands[0]
    assert command.delegation_id == "forbidden"
    assert command.content == "Delegation is disabled in translation mode"
    assert len(command.content.encode()) <= 500
    await manager.aclose()


def test_interrupted_recap_discards_old_answer_and_accepts_correction() -> None:
    recap = Recap()
    recap.observe(Transcript("user", "calcola 2+2", 0, 10), "calcola 2+2")
    recap.observe(Transcript("assistant", "quattro", 11, 20), "calcola 2+2")
    recap.interrupt()
    recap.observe(Transcript("assistant", "late reply", 21, 30), "calcola 2+2")
    assert not recap.latest_reply and recap.interrupted
    recap.observe(Transcript("user", "no, calculate 3+3", 31, 40), "no, calculate 3+3")
    assert recap.latest_request == "no, calculate 3+3"
    recap.resume()
    recap.observe(Transcript("assistant", "six", 41, 50), "no, calculate 3+3")
    assert str(recap.latest_reply) == "six" and not bool(recap.interrupted)
    recap.observe(Transcript("user", "x" * 4000, 51, 60), "x" * 4000)
    assert len(recap.latest_request.encode()) <= 600


@pytest.mark.parametrize("status", ["idle", "completed", "cancelled", "failed", "running"])
async def test_interrupt_marks_recap_only_for_running_delegation(
    status: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager = SessionManager(FakeProvider(), Settings())
    session = manager.create()
    session.recap.observe(Transcript("assistant", "Previous answer", 1, 2), "A request")
    session.delegation.status = status
    with caplog.at_level("INFO", logger="voice_delegate.session.manager"):
        manager.interrupt(session)
    assert ("Delegation interrupted: source=client" in caplog.text) is (status == "running")
    assert "Previous answer" not in caplog.text
    assert session.recap.interrupted is (status == "running")
    assert session.recap.latest_reply == ("" if status == "running" else "Previous answer")
    await manager.aclose()


def test_recap_assembles_live_reply_fragments_and_resets_for_next_request() -> None:
    recap = Recap()
    recap.observe(Transcript("user", "question", 0, 10), "question")
    for index, text in enumerate(["The answer", " is eight", "."]):
        recap.observe(Transcript("assistant", text, 20 + index, 21 + index), "question")
    assert recap.latest_reply == "The answer is eight."
    recap.observe(Transcript("assistant", "The answer is eight.", 0, 0, True), "question")
    assert recap.latest_reply == "The answer is eight."
    recap.observe(Transcript("user", "next", 30, 40), "next")
    recap.observe(Transcript("assistant", "New reply", 41, 50), "next")
    assert recap.latest_reply == "New reply"
