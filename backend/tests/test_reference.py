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
    assert answer.sources
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
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://localhost:5173"},
        ) as client,
    ):
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


async def test_repeated_searches_keep_citation_identity_and_remap_final_indices() -> None:
    import json

    from langchain_core.messages import AIMessage, AnyMessage

    class SearchTwice:
        def __init__(self) -> None:
            self.calls = 0
            self.expected: list[str] = []

        async def respond(self, messages: list[AnyMessage]) -> AIMessage:
            self.calls += 1
            if self.calls <= 2:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_documentation",
                            "args": {
                                "query": "fallback history" if self.calls == 1 else "sqlite quotas"
                            },
                            "id": str(self.calls),
                        }
                    ],
                )
            sources = json.loads(str(messages[-1].content))["sources"]
            self.expected = [source["id"] for source in sources]
            return AIMessage(content=f"SQLite evidence [{sources[0]['citation']}]")

    planner = SearchTwice()
    result = await LangGraphWorker(planner).delegate_task("Search twice", "")
    assert result.text == "SQLite evidence [1]"
    assert [source.id for source in result.sources] == planner.expected


async def test_worker_rejects_citations_without_retrieved_evidence() -> None:
    from langchain_core.messages import AIMessage, AnyMessage

    class InventedCitation:
        async def respond(self, messages: list[AnyMessage]) -> AIMessage:
            return AIMessage(content="Unsupported [99]")

    result = await LangGraphWorker(InventedCitation()).delegate_task("question", "")
    assert "task incomplete" in result.text
    assert result.sources == ()


async def test_architecture_command_retrieves_the_document_overview() -> None:
    result = await LangGraphWorker(OfflinePlanner()).delegate_task("architecture", "")
    assert result.sources
    assert result.sources[0].path == "docs/architecture.md"
    assert result.sources[0].section == "Boundaries"
    assert "WebRTC" in result.text
    assert "FastAPI" in result.text
    assert search("architettura") == search("architecture")
    assert search("boundaries")[0].section == "Boundaries"
    assert search("zzzzunfindable") == ()
