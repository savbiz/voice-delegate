"""Canonical adapter names and actual Chat Completions payloads, with no provider calls."""

import json
from typing import Any

import httpx
import pytest
from langchain_core.messages import AnyMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError
from voice_delegate.config import Settings
from voice_delegate_agent import graph
from voice_delegate_agent.model_config import DEFAULT_WORKER_MODEL


def test_adapter_alias_precedence_and_programmatic_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_VOICE_PROVIDER", "realtime")
    assert Settings().voice_provider == "realtime"
    monkeypatch.setenv("VOICE_ADAPTER", "live")
    assert Settings().voice_provider == "live"
    # Explicit constructor settings retain their normal priority over the environment.
    assert Settings(voice_provider="realtime").voice_provider == "realtime"
    monkeypatch.setenv("VOICE_ADAPTER", "unsupported")
    with pytest.raises(ValidationError):
        Settings()


def test_default_worker_model_is_luna_and_explicit_override_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VOICE_WORKER_MODEL", raising=False)
    assert Settings().worker_model == DEFAULT_WORKER_MODEL == "gpt-6-luna"
    monkeypatch.setenv("VOICE_WORKER_MODEL", "explicit-test-model")
    assert Settings().worker_model == "explicit-test-model"


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-4.1-mini"])
async def test_worker_serializes_supported_tool_and_final_requests(
    model: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        captured.append(body)
        message: dict[str, Any] = {"role": "assistant", "content": "4"}
        if "tools" in body:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_fixture",
                        "type": "function",
                        "function": {
                            "name": "calculate",
                            "arguments": json.dumps({"expression": "2+2"}),
                        },
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-fixture",
                "object": "chat.completion",
                "created": 1,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if "tools" in body else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:

        def local_client(**kwargs: Any) -> ChatOpenAI:
            return ChatOpenAI(**kwargs, http_async_client=http)

        monkeypatch.setattr(graph, "ChatOpenAI", local_client)
        planner = graph.OpenAIPlanner("offline-fixture", model)
        try:
            messages: list[AnyMessage] = [HumanMessage(content="calculate 2+2")]
            answer = await planner.respond(messages)
            assert answer.tool_calls[0]["name"] == "calculate"
            assert answer.tool_calls[0]["args"] == {"expression": "2+2"}
            assert (await planner.respond_final(messages)).content == "4"
        finally:
            await planner.aclose()
    assert len(captured) == 2
    for body in captured:
        assert body["model"] == model
        assert body["max_completion_tokens"] == 1000
        if model == "gpt-6-luna":
            assert body["reasoning_effort"] == "none"
        else:
            assert "reasoning_effort" not in body
    assert captured[0]["parallel_tool_calls"] is False
    assert "tools" not in captured[1]
