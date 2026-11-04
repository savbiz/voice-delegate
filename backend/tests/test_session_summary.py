"""Opt-in generated recap at user close: bounded, best effort and included in the estimate."""

import asyncio

import pytest
from conftest import ASGIClientFactory
from pydantic import SecretStr
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import Transcript
from voice_delegate.session import manager as manager_module
from voice_delegate.session.manager import SessionManager
from voice_delegate.session.models import Session
from voice_delegate_agent.summary import SUMMARY_MAX_CHARS, clean_summary
from voice_delegate_agent.usage import Usage, external_call, note

from test_support import eventually


class FakeSummarizer:
    def __init__(self, answer: str = "You asked about the match.", fail: bool = False) -> None:
        self.answer = answer
        self.fail = fail
        self.transcripts: list[str] = []
        self.closed = False

    async def summarize(self, transcript: str) -> str:
        self.transcripts.append(transcript)
        with external_call("worker_calls"):
            note(Usage(input_tokens=120, output_tokens=30))
            if self.fail:
                message = "provider down"
                raise RuntimeError(message)
        return self.answer

    async def aclose(self) -> None:
        self.closed = True


async def spoken_session(manager: SessionManager, provider: FakeProvider) -> Session:
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    for event in (
        Transcript("user", "Che ha fatto ieri la Juve?", 0, 0, committed=True),
        Transcript("assistant", "Controllo subito.", 0, 0, committed=True),
    ):
        provider.connections[0].queue.put_nowait(event)
    await eventually(lambda: len(session.history.turns) == 2)
    return session


async def test_user_close_summarizes_once_and_counts_the_call() -> None:
    provider, summarizer = FakeProvider(), FakeSummarizer()
    manager = SessionManager(provider, Settings(cost_estimates=True), summarizer=summarizer)
    session = await spoken_session(manager, provider)
    await manager.close(session, summarize=True)
    await manager.close(session, summarize=True)
    assert session.summary == "You asked about the match."
    assert len(summarizer.transcripts) == 1
    assert "user: Che ha fatto ieri la Juve?" in summarizer.transcripts[0]
    assert "assistant: Controllo subito." in summarizer.transcripts[0]
    assert session.costs is not None
    final = session.costs.snapshot()
    assert final.final
    assert final.usage.worker_calls == 1
    assert final.usage.input_tokens == 120
    await manager.aclose()
    assert summarizer.closed


async def test_expiry_close_silence_and_failures_keep_the_extractive_recap() -> None:
    provider, summarizer = FakeProvider(), FakeSummarizer()
    manager = SessionManager(provider, Settings(cost_estimates=True), summarizer=summarizer)
    expired = await spoken_session(manager, provider)
    await manager.close(expired)
    assert expired.summary is None
    silent = manager.create()
    await manager.close(silent, summarize=True)
    assert silent.summary is None
    assert summarizer.transcripts == []
    failing = FakeSummarizer(fail=True)
    manager.summarizer = failing
    provider.connections.clear()
    broken = await spoken_session(manager, provider)
    assert await manager.close(broken, summarize=True) is True
    assert broken.summary is None
    assert broken.costs is not None
    assert broken.costs.snapshot().usage.uncertain
    await manager.aclose()


@pytest.mark.parametrize(
    ("overrides", "built"),
    [
        ({}, False),
        ({"session_summary": True}, False),
        ({"session_summary": True, "worker_mode": "openai"}, True),
        ({"worker_mode": "openai"}, False),
    ],
)
async def test_summary_is_opt_in_and_needs_an_openai_key(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, object], built: bool
) -> None:
    created: list[tuple[str, str]] = []

    class Recording(FakeSummarizer):
        def __init__(self, key: str, model: str) -> None:
            super().__init__()
            created.append((key, model))

    monkeypatch.setattr(manager_module, "OpenAISummarizer", Recording)
    settings = Settings(openai_api_key=SecretStr("sk-test"), **overrides)  # type: ignore[arg-type]
    manager = SessionManager(FakeProvider(), settings)
    assert (manager.summarizer is not None) is built
    assert created == ([("sk-test", settings.worker_model)] if built else [])
    await manager.aclose()


async def test_close_route_returns_the_summary(
    monkeypatch: pytest.MonkeyPatch, asgi_client: ASGIClientFactory
) -> None:
    from voice_delegate.api.app import create_app

    monkeypatch.setattr(manager_module, "OpenAISummarizer", lambda _key, _model: FakeSummarizer())
    settings = Settings(
        session_summary=True, worker_mode="openai", openai_api_key=SecretStr("sk-test")
    )
    provider = FakeProvider()
    app = create_app(settings, provider)
    async with asgi_client(app) as client:
        client.headers["Origin"] = "http://localhost:5173"
        for spoken, expected in ((False, None), (True, "You asked about the match.")):
            created = (await client.post("/api/sessions")).json()
            headers = {"X-Session-Key": created["key"]}
            path = "/api/sessions/" + created["id"]
            offer = await client.post(path + "/offer", json={"sdp": "v=0\r\n"}, headers=headers)
            assert offer.status_code == 200
            if spoken:
                provider.connections[-1].queue.put_nowait(
                    Transcript("user", "Che ha fatto la Juve?", 0, 0, committed=True)
                )

                async def heard(path: str = path, headers: dict[str, str] = headers) -> bool:
                    beat = await client.post(path + "/heartbeat", headers=headers)
                    return bool(beat.json()["recap"]["latest_request"])

                for _ in range(50):
                    if await heard():
                        break
                    await asyncio.sleep(0.02)
                assert await heard()
            closed = (await client.post(path + "/close", headers=headers)).json()
            # Without user speech there is nothing to summarize: the client keeps the recap.
            assert closed["summary"] == expected
            assert closed["costs"]["final"] is True


def test_summary_text_is_plain_and_bounded() -> None:
    assert clean_summary("  Two\nlines  ") == "Two lines"
    assert clean_summary(["not", "text"]) == ""
    long = clean_summary("word " * 400)
    assert len(long) == SUMMARY_MAX_CHARS
    assert long.endswith("…")
