"""Canonical adapter names and actual Chat Completions payloads, with no provider calls."""

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AnyMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError
from voice_delegate.config import Settings, load_settings
from voice_delegate_agent import graph
from voice_delegate_agent.model_config import DEFAULT_WORKER_MODEL


def test_adapter_alias_precedence_and_programmatic_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canonical aliases win within a source while constructor overrides retain priority."""
    monkeypatch.setenv("VOICE_VOICE_PROVIDER", "realtime")
    assert Settings().voice_provider == "openai"
    monkeypatch.setenv("VOICE_ADAPTER", "azure")
    monkeypatch.setenv("VOICE_AZURE_ENDPOINT", "https://test.openai.azure.com")
    monkeypatch.setenv("VOICE_AZURE_API_KEY", "fixture")
    assert Settings().voice_provider == "azure"
    # Explicit constructor settings retain their normal priority over the environment.
    assert Settings.model_validate({"voice_provider": "realtime"}).voice_provider == "openai"
    monkeypatch.setenv("VOICE_ADAPTER", "unsupported")
    with pytest.raises(ValidationError):
        Settings()


def test_default_worker_model_is_luna_and_explicit_override_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new default must not override an explicitly selected worker model."""
    monkeypatch.delenv("VOICE_WORKER_MODEL", raising=False)
    assert Settings().worker_model == DEFAULT_WORKER_MODEL == "gpt-6-luna"
    monkeypatch.setenv("VOICE_WORKER_MODEL", "explicit-test-model")
    assert Settings().worker_model == "explicit-test-model"


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-4.1-mini"])
async def test_worker_serializes_supported_tool_and_final_requests(
    model: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the actual SDK serialization with a fake HTTP transport."""
    captured: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Return deterministic completion envelopes and capture only fixture requests."""
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
            """Inject a fake transport into the real SDK client."""
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


def test_process_adapter_overrides_dotenv_without_mutating_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in list(os.environ):
        if key.startswith("VOICE_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("VOICE_ADAPTER=azure\nVOICE_WORKER_MODEL=file-model\n")
    monkeypatch.setenv("VOICE_ADAPTER", "openai")
    assert load_settings().voice_provider == "openai"
    assert load_settings().worker_model == "file-model"
    assert "VOICE_WORKER_MODEL" not in os.environ


def test_removed_adapter_alias_fails_with_its_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("VOICE_VOICE_PROVIDER=azure\n")
    with pytest.raises(ValueError, match="use VOICE_ADAPTER"):
        load_settings()
    (tmp_path / ".env").write_text("voice_allowed_origin=https://frontend.example\n")
    with pytest.raises(ValueError, match="use VOICE_ALLOWED_ORIGINS"):
        load_settings()
