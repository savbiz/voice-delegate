"""Evidence must be actual bundled text, and citations cannot survive cancellation."""

import hashlib
from pathlib import Path

import httpx
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.delegation.contracts import DelegationInput
from voice_delegate.delegation.runner import DelegationRunner, DelegationState
from voice_delegate.providers.fake import FakeConnection, FakeProvider
from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner
from voice_delegate_agent.reference import WorkerResult, corpus, search, source_by_id


def test_bundled_sources_match_reviewed_project_files() -> None:
    root = Path(__file__).resolve().parents[2]
    assert len({s.id for s in corpus()}) == len(corpus())
    for source in corpus():
        assert source.text in (root / source.path).read_text()
        digest = hashlib.sha256(
            (source.path + "\n" + source.section + "\n" + source.text).encode()
        ).hexdigest()
        assert digest == source.digest
    assert any("2048 tokens" in s.text for s in search("fallback history"))
    assert search("zzzzunfindable") == ()
    assert search("x" * 501) == ()
    assert source_by_id("../../.env") is None


async def test_documentation_worker_preserves_citations_outside_spoken_budget() -> None:
    worker = LangGraphWorker(OfflinePlanner())
    answer = await worker.delegate_task("docs fallback history", "")
    assert isinstance(answer, WorkerResult) and answer.sources
    assert "[1]" in answer.text
    runner = DelegationRunner(worker, budget=16)
    state = DelegationState()
    connection = FakeConnection()
    runner.start(
        state, "docs1", DelegationInput(goal="docs fallback history"), connection, lambda: True
    )
    assert state.task is not None
    await state.task
    assert state.status == "completed" and state.sources
    assert state.sources == answer.sources
    assert connection.commands[0].content != answer.text
    assert len(connection.commands[0].content.encode()) <= 500
    runner.cancel(state)
    assert not state.sources
    await runner.aclose()


def test_worker_result_equality_includes_sources() -> None:
    from dataclasses import FrozenInstanceError

    import pytest

    first, second = corpus()[:2]
    result = WorkerResult("same text", (first,))
    assert result != WorkerResult("same text", (second,))
    with pytest.raises(FrozenInstanceError):
        result.text = "changed"  # type: ignore[misc]


async def test_authenticated_search_and_inspect_source_without_voice() -> None:
    from pydantic import SecretStr

    provider = FakeProvider()
    app = create_app(Settings(access_token=SecretStr("test-access")), provider)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://localhost:5173"},
        ) as client:
            path = "/api/reference/search"
            assert (await client.post(path, json={"query": "fallback"})).status_code == 401
            client.headers["Authorization"] = "Bearer test-access"
            response = await client.post(path, json={"query": "fallback history"})
            assert response.status_code == 200
            first = response.json()["sources"][0]
            detail = await client.post("/api/reference/" + first["id"])
            assert detail.json() == first
            assert (await client.post(path, json={"query": "x" * 501})).status_code == 422
            assert not (await client.post(path, json={"query": "zzzzunfindable"})).json()["sources"]
            assert not provider.connections


def test_demo_aliases_and_stop_words_preserve_retrieval() -> None:
    from voice_delegate_agent.reference import terms

    assert terms("come funziona la cronologia e le interruzioni") == {
        "funziona",
        "history",
        "interruptions",
    }
    assert terms("history replays") == {"history", "replay"}
    assert search("cronologia") == search("history")
