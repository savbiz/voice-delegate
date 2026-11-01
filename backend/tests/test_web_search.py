"""Opt-in search contracts exercise real tools with deterministic HTTP transports."""

import asyncio
import json
from dataclasses import asdict, replace
from typing import Any, Literal

import httpx
import pytest
from conftest import ASGIClientFactory
from pydantic import SecretStr, ValidationError
from voice_delegate.config import Settings
from voice_delegate.delegation.planner import build_planner
from voice_delegate.scaling.remote import RemoteWorker
from voice_delegate.scaling.worker_service import JobOutput
from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner, worker_instructions
from voice_delegate_agent.tools import TOOLS
from voice_delegate_agent.web_search import (
    RESPONSE_BYTES,
    TavilySearch,
    domain_name,
    source_url,
    verified_web_source,
    web_source,
)


async def test_search_bounds_filters_and_deduplicates_results() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        rows = [
            {"url": "https://example.org/a#one", "title": "A" * 200, "content": "x" * 900},
            {"url": "https://example.org/a#two", "title": "duplicate", "content": "other"},
            {"url": "https://evil-example.org/", "title": "wrong domain", "content": "skip"},
            {"url": "http://example.org/", "title": "insecure", "content": "skip"},
            {"url": "https://sub.example.org/b", "title": "B", "content": "quoted\x00 evidence"},
            {"url": "https://example.org/c", "title": "C", "content": "third"},
            {"url": "https://example.org/d", "title": "D", "content": "fourth"},
        ]
        return httpx.Response(200, json={"results": rows})

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    tool = TavilySearch("test-value", domains=("example.org",), http=http)
    try:
        result = json.loads(await tool.search("latest public documentation"))
        assert result["status"] == "found"
        assert len(result["sources"]) == 3
        first = result["sources"][0]
        assert first["path"] == "https://example.org/a"
        assert len(first["title"]) == 160
        assert len(first["text"]) == 400
        assert result["sources"][1]["text"] == "quoted evidence"
        assert len(requests) == 1
        request = requests[0]
        assert str(request.url) == "https://api.tavily.com/search"
        body = json.loads(request.content)
        assert body["max_results"] == 3
        assert body["search_depth"] == "basic"
        assert body["include_domains"] == ["example.org"]
        assert body["include_answer"] is body["include_raw_content"] is False
        assert body["auto_parameters"] is False
    finally:
        await tool.aclose()
    assert http.is_closed


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://example.org/",
        "https://localhost/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://127.1/",
        "https://0x7f.1/",
        "https://user:pass@example.org/",
        "https://example.org:8443/",
        "https://a.internal/",
        "https://example.org/\n",
        "https://example.org/\u202e",
        "https://example.org\\@other.org/",
    ],
)
def test_web_evidence_rejects_unsafe_urls(url: str) -> None:
    assert source_url(url) is None


@pytest.mark.parametrize(
    "domain",
    ["*.example.org", "localhost", "127.0.0.1", "a.local", "a..org", "https://example.org"],
)
def test_domain_allowlist_requires_canonical_dns(domain: str) -> None:
    with pytest.raises(ValueError):
        domain_name(domain)


@pytest.mark.parametrize("failure", ["status", "oversize", "json", "shape", "network", "redirect"])
async def test_provider_failure_uses_documentation_fallback(failure: str) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "network":
            raise httpx.ConnectError("private detail", request=request)
        if failure == "status":
            return httpx.Response(429)
        if failure == "oversize":
            return httpx.Response(200, content=b"x" * (RESPONSE_BYTES + 1))
        if failure == "json":
            return httpx.Response(200, content=b"not-json")
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://other.org/"})
        return httpx.Response(200, json={"results": None})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        result = json.loads(await TavilySearch("test-value", http=http).search("fallback"))
    assert calls == 1
    assert result["status"] == "web_unavailable"
    assert result["sources"]
    assert all(not source["id"].startswith("web-") for source in result["sources"])
    assert "private detail" not in json.dumps(result)


async def test_total_timeout_and_cancellation_are_distinct() -> None:
    waiting = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        waiting.set()
        await asyncio.Event().wait()
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        result = json.loads(
            await TavilySearch("test-value", timeout=0.01, http=http).search("fallback")
        )
        assert result["status"] == "web_unavailable"
        waiting.clear()
        pending = asyncio.create_task(TavilySearch("test-value", http=http).search("fallback"))
        await waiting.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending


async def test_flag_off_has_no_web_client_or_tool() -> None:
    runtime = build_planner(Settings())
    try:
        assert runtime.web is None
        assert [tool.name for tool in runtime.tools] == ["calculate", "search_documentation"]
        result = await runtime.worker(4).delegate_task("calculate 2+2", "")
        assert result.text == "Offline worker result: 4"
    finally:
        await runtime.aclose()
    with pytest.raises(ValidationError, match="TAVILY_API_KEY"):
        Settings(web_search=True)


async def test_graph_keeps_cited_web_evidence() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.org/news",
                        "title": "Public notice",
                        "content": "A public update.",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        web = TavilySearch("test-value", http=http)
        worker = LangGraphWorker(
            OfflinePlanner(web_search=True),
            tools=(*TOOLS, web.tool()),
            instructions=worker_instructions(True),
        )
        result = await worker.delegate_task("web latest public update", "")
    assert result.status == "completed"
    assert "[1]" in result.text
    assert len(result.sources) == 1
    assert verified_web_source(result.sources[0])


@pytest.mark.parametrize("enabled", [False, True])
async def test_remote_worker_preserves_only_enabled_verified_web_sources(enabled: bool) -> None:
    source = web_source("https://example.org/news", "Public notice", "A public update.")
    assert source is not None
    methods: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method != "GET":
            return httpx.Response(202 if request.method == "POST" else 204)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "text": "Update [1]",
                "source_ids": [source.id],
                "web_sources": [asdict(source)],
            },
        )

    settings = Settings(web_search=enabled, tavily_api_key=SecretStr("test-value"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        worker = RemoteWorker(settings, http=http)
        if enabled:
            result = await worker.delegate_task("current update", "")
            assert result.sources == (source,)
        else:
            with pytest.raises(RuntimeError, match="not enabled"):
                await worker.delegate_task("current update", "")
    assert methods == ["POST", "GET", "DELETE"]
    with pytest.raises(ValidationError, match="Invalid web evidence"):
        JobOutput(status="completed", web_sources=(replace(source, digest="forged"),))


@pytest.mark.parametrize("payload", [{"results": []}, {"results": [{"url": 7}]}])
async def test_empty_or_invalid_rows_are_explicit(payload: dict[str, Any]) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        result = json.loads(await TavilySearch("test-value", http=http).search("current update"))
    assert result["status"] == "no_results"
    assert result["sources"] == []


async def test_private_service_transports_web_evidence_end_to_end(
    asgi_client: ASGIClientFactory,
) -> None:
    from voice_delegate.scaling.worker_service import create_worker_app

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.org/notice",
                        "title": "Notice",
                        "content": "A public update.",
                    }
                ]
            },
        )

    settings = Settings(
        web_search=True,
        tavily_api_key=SecretStr("test-value"),
        worker_service_token=SecretStr("x" * 32),
        worker_service_url="http://localhost",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        web = TavilySearch("test-value", http=http)
        graph = LangGraphWorker(
            OfflinePlanner(web_search=True),
            tools=(*TOOLS, web.tool()),
            instructions=worker_instructions(True),
        )
        app = create_worker_app(settings, graph)
        async with asgi_client(app) as service:
            result = await RemoteWorker(settings, http=service).delegate_task(
                "web public notice", ""
            )
    assert result.status == "completed"
    assert "[1]" in result.text
    assert len(result.sources) == 1
    assert result.sources[0].path == "https://example.org/notice"


async def test_enabled_factory_owns_search_tool_and_client() -> None:
    runtime = build_planner(Settings(web_search=True, tavily_api_key=SecretStr("test-value")))
    assert runtime.web is not None
    assert [tool.name for tool in runtime.tools] == [
        "calculate",
        "search_documentation",
        "web_search",
    ]
    assert "Search the web last" in runtime.instructions
    await runtime.aclose()
    assert runtime.web.http.is_closed


def test_clipped_whitespace_does_not_invalidate_web_evidence() -> None:
    source = web_source("https://example.org/notice", "word " * 60, "word " * 200)
    assert source is not None
    assert len(source.title) == 159
    assert len(source.text) == 399
    assert not source.title.endswith(" ") and not source.text.endswith(" ")
    assert verified_web_source(source)
    assert JobOutput(status="completed", web_sources=(source,)).web_sources == (source,)


@pytest.mark.parametrize("mode", ["offline", "openai", "decisions"])
async def test_voice_advertises_natural_search_only_with_a_capable_planner(
    mode: Literal["offline", "openai", "decisions"],
) -> None:
    from voice_delegate.providers.fake import FakeProvider
    from voice_delegate.session.manager import SessionManager

    settings = Settings(
        worker_mode=mode,
        web_search=True,
        tavily_api_key=SecretStr("test-value"),
        openai_api_key=SecretStr("test-model-value"),
    )
    manager = SessionManager(FakeProvider(), settings)
    try:
        instructions = manager.config().instructions
        assert ("read-only public web search" in instructions) is (mode != "offline")
    finally:
        await manager.aclose()
