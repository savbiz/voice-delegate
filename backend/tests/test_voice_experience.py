"""Language configuration and correction state; real pronunciation is a live gate."""

import httpx
import pytest
from conftest import eventually
from voice_delegate.config import Settings
from voice_delegate.providers.base import SidebandSocket
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import (
    DelegationRequested,
    ProviderError,
    SessionConfig,
    Transcript,
)
from voice_delegate.providers.realtime import OpenAIRealtimeProvider
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.preferences import VoicePreferences
from voice_delegate.session.summary import Recap


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


async def test_realtime_uses_fixed_openai_origin_and_bearer_auth() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.openai.com"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert "api-key" not in request.headers
        if request.url.path.endswith("/hangup"):
            return httpx.Response(200)
        return httpx.Response(201, text="v=0\r\n", headers={"Location": "/calls/rtc_test"})

    class FixtureProvider(OpenAIRealtimeProvider):
        async def _attach(self, call_id: str) -> SidebandSocket:
            raise OSError("socket unavailable")

    provider = FixtureProvider(
        "test-key", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ProviderError, match="OpenAI Realtime connection failed"):
        await provider.connect(
            config=SessionConfig("gpt-realtime", "marin", "test"), offer_sdp="v=0\r\n"
        )
    assert [r.url.path for r in requests] == [
        "/v1/realtime/calls",
        "/v1/realtime/calls/rtc_test/hangup",
    ]
    await provider.aclose()


@pytest.mark.parametrize("status", ["idle", "completed", "cancelled", "failed", "running"])
async def test_interrupt_marks_recap_only_for_running_delegation(status: str) -> None:
    manager = SessionManager(FakeProvider(), Settings())
    session = manager.create()
    session.recap.observe(Transcript("assistant", "Previous answer", 1, 2), "A request")
    session.delegation.status = status
    manager.interrupt(session)
    assert session.recap.interrupted is (status == "running")
    assert session.recap.latest_reply == ("" if status == "running" else "Previous answer")
    await manager.aclose()
