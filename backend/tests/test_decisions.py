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


async def test_choice_http_contract_and_distribution() -> None:
    from voice_delegate.decisions import Choice, Option

    seen: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "answers": [
                    {
                        "type": "choice",
                        "name": "tool",
                        "choice": "calculate",
                        "confidence": 0.9,
                        "probabilities": [
                            {"value": "calculate", "probability": 0.9},
                            {"value": "direct", "probability": 0.1},
                        ],
                    }
                ],
                "usage": {"input_tokens": 24},
            },
        )

    decider = OpenAIDecider(
        "fixture", http=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )
    try:
        result = await decider.decide(
            "untrusted input",
            (
                Choice(
                    "tool",
                    "Choose a tool",
                    (Option("calculate", "Arithmetic"), Option("direct", "Answer")),
                ),
            ),
        )
        assert result.choices["tool"].value == "calculate"
        assert result.choices["tool"].probabilities == {"calculate": 0.9, "direct": 0.1}
        assert result.input_tokens == 24
        assert seen[0]["questions"] == [
            {
                "type": "choice",
                "name": "tool",
                "instructions": "Choose a tool",
                "choices": [
                    {"value": "calculate", "description": "Arithmetic"},
                    {"value": "direct", "description": "Answer"},
                ],
            }
        ]
    finally:
        await decider.aclose()


@pytest.mark.parametrize(
    "invalid", ["unknown", "duplicate", "nan", "sum", "type", "missing", "refusal"]
)
async def test_invalid_choice_responses_and_refusals(invalid: str) -> None:
    from voice_delegate.decisions import Choice, Option

    answer: dict[str, object] = {
        "type": "choice",
        "name": "tool",
        "choice": "a",
        "confidence": 0.9,
        "probabilities": [{"value": "a", "probability": 0.9}, {"value": "b", "probability": 0.1}],
    }
    if invalid == "unknown":
        answer["choice"] = "unknown"
    if invalid == "duplicate":
        answer["probabilities"] = [
            {"value": "a", "probability": 0.9},
            {"value": "a", "probability": 0.1},
        ]
    if invalid == "nan":
        answer["confidence"] = float("nan")
    if invalid == "sum":
        answer["probabilities"] = [
            {"value": "a", "probability": 0.9},
            {"value": "b", "probability": 0.9},
        ]
    if invalid == "type":
        answer = {"type": "predicate", "name": "tool", "probability": 0.9}
    if invalid == "missing":
        answer.pop("probabilities")
    if invalid == "refusal":
        answer = {"type": "refusal", "name": "tool"}
    decider = OpenAIDecider(
        "fixture",
        http=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    content=json.dumps(
                        {"answers": [answer], "usage": {"input_tokens": 10}}
                    ).encode(),
                )
            )
        ),
    )
    try:
        if invalid == "refusal":
            result = await decider.decide(
                "data", (Choice("tool", "Choose", (Option("a"), Option("b"))),)
            )
            assert result.refused == ("tool",) and result.choices == {}
        else:
            with pytest.raises(DecisionError):
                await decider.decide(
                    "data", (Choice("tool", "Choose", (Option("a"), Option("b"))),)
                )
    finally:
        await decider.aclose()
