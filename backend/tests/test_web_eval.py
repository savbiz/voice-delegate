"""Versioned external-information cases exercise search and citation wiring offline."""

import json
from pathlib import Path

import httpx
import pytest
from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner, worker_instructions
from voice_delegate_agent.tools import TOOLS
from voice_delegate_agent.web_search import TavilySearch

CASES: list[dict[str, str]] = json.loads(
    (Path(__file__).resolve().parents[2] / "evals/data/web-v1.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
async def test_external_question_uses_web_and_keeps_labelled_source(case: dict[str, str]) -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["query"])
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": case["url"], "title": case["title"], "content": case["content"]}
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
        result = await worker.delegate_task(case["goal"], "")
    assert calls == [case["goal"].removeprefix("web ")]
    assert result.status == "completed"
    assert case["content"] in result.text
    assert "[1]" in result.text
    assert [source.path for source in result.sources] == [case["url"]]
