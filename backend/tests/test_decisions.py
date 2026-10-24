"""HTTP contract tests use a local mock transport, never a live classification."""

import asyncio
import json

import httpx
import pytest
from voice_delegate.decisions import DecisionError, Predicate
from voice_delegate.decisions.openai import OpenAIDecider


async def test_predicate_contract_refusals_and_usage() -> None:
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "answers": [
                    {"name": "cancel", "type": "predicate", "probability": 0.9},
                    {"name": "relevant", "type": "refusal"},
                ],
                "usage": {"input_tokens": 12},
            },
        )

    decider = OpenAIDecider(
        "fixture", http=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )
    try:
        result = await decider.decide(
            "input data", (Predicate("cancel", "Cancel?"), Predicate("relevant", "Relevant?"))
        )
        assert result.probabilities == {"cancel": 0.9}
        assert result.input_tokens == 12
        assert requests == [
            {
                "model": "gpt-6-luna",
                "input": "input data",
                "questions": [
                    {"type": "predicate", "name": "cancel", "instructions": "Cancel?"},
                    {"type": "predicate", "name": "relevant", "instructions": "Relevant?"},
                ],
            }
        ]
    finally:
        await decider.aclose()


@pytest.mark.parametrize(
    "body",
    [
        b"invalid",
        b"x" * 65537,
        json.dumps({"answers": [], "usage": {"input_tokens": 1}}).encode(),
        json.dumps(
            {
                "answers": [{"name": "cancel", "type": "predicate", "probability": 2}],
                "usage": {"input_tokens": 1},
            }
        ).encode(),
        json.dumps(
            {
                "answers": [{"name": "cancel", "type": "predicate", "probability": 1}],
                "usage": {"input_tokens": -1},
            }
        ).encode(),
    ],
)
async def test_invalid_response_is_sanitized(body: bytes) -> None:
    decider = OpenAIDecider(
        "fixture",
        http=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
        ),
    )
    try:
        with pytest.raises(DecisionError, match="Decision"):
            await decider.decide("private fixture", (Predicate("cancel", "Cancel?"),))
    finally:
        await decider.aclose()


async def test_timeout_is_bounded_and_cancelled_error_propagates() -> None:
    entered = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        entered.set()
        await asyncio.Event().wait()
        return httpx.Response(200)

    decider = OpenAIDecider(
        "fixture", timeout=0.01, http=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )
    try:
        with pytest.raises(DecisionError):
            await decider.decide("data", (Predicate("cancel", "Cancel?"),))
        entered.clear()
        task = asyncio.create_task(decider.decide("data", (Predicate("cancel", "Cancel?"),)))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(DecisionError):
            await decider.decide("x" * 32769, (Predicate("cancel", "Cancel?"),))
    finally:
        await decider.aclose()
