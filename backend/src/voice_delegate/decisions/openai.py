"""Bounded Decisions HTTP contract, checked against the public reference on 2026-10-26."""

import asyncio
import json
import math
from dataclasses import asdict
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import Choice, Decision, DecisionError, Predicate, Question, Selection


class PredicateAnswer(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    type: Literal["predicate"]
    name: str
    probability: float = Field(ge=0, le=1)


class Probability(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    value: str = Field(strict=True)
    probability: float = Field(ge=0, le=1)


class ChoiceAnswer(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    type: Literal["choice"]
    name: str
    choice: str = Field(strict=True)
    confidence: float = Field(ge=0, le=1)
    probabilities: list[Probability] = Field(min_length=2, max_length=32)


class Refusal(BaseModel):
    type: Literal["refusal"]
    name: str


type Answer = Annotated[PredicateAnswer | ChoiceAnswer | Refusal, Field(discriminator="type")]


class Usage(BaseModel):
    input_tokens: int = Field(ge=0, le=1000000)


class Response(BaseModel):
    answers: list[Answer] = Field(max_length=4)
    usage: Usage


class OpenAIDecider:
    """No retries, redirects, payload logging or unbounded response buffering."""

    def __init__(
        self, key: str, *, timeout: float = 1, http: httpx.AsyncClient | None = None
    ) -> None:
        self._key = key
        self._http = http or httpx.AsyncClient(timeout=timeout)
        self._timeout = timeout

    async def decide(self, text: str, questions: tuple[Question, ...]) -> Decision:
        if (
            len(text.encode()) > 32768
            or not 1 <= len(questions) <= 4
            or len({q.name for q in questions}) != len(questions)
            or any(
                not 2 <= len(q.choices) <= 32 or len({o.value for o in q.choices}) != len(q.choices)
                for q in questions
                if isinstance(q, Choice)
            )
        ):
            message = "Decision input exceeds budget"
            raise DecisionError(message)
        body = {
            "model": "gpt-6-luna",
            "input": text,
            "questions": [
                {"type": "predicate" if isinstance(q, Predicate) else "choice", **asdict(q)}
                for q in questions
            ],
        }
        if len(json.dumps(body).encode()) > 65536:
            message = "Decision input exceeds budget"
            raise DecisionError(message)
        try:
            async with (
                asyncio.timeout(self._timeout),
                self._http.stream(
                    "POST",
                    "https://api.openai.com/v1/decisions",
                    headers={"Authorization": "Bearer " + self._key},
                    json=body,
                ) as response,
            ):
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    data.extend(chunk)
                    if len(data) > 65536:
                        message = "Decision response exceeds budget"
                        raise DecisionError(message)
                result = Response.model_validate_json(data)
        except (httpx.HTTPError, TimeoutError, ValidationError) as exc:
            message = "Decision unavailable"
            raise DecisionError(message) from exc
        if [a.name for a in result.answers] != [q.name for q in questions]:
            message = "Decision answer mismatch"
            raise DecisionError(message)
        probabilities: dict[str, float] = {}
        choices: dict[str, Selection] = {}
        refused = []
        for question, answer in zip(questions, result.answers, strict=True):
            if isinstance(answer, Refusal):
                refused.append(answer.name)
            elif isinstance(question, Predicate) and isinstance(answer, PredicateAnswer):
                probabilities[answer.name] = answer.probability
            elif isinstance(question, Choice) and isinstance(answer, ChoiceAnswer):
                values = {o.value for o in question.choices}
                distribution = {p.value: p.probability for p in answer.probabilities}
                if (
                    answer.choice not in values
                    or set(distribution) != values
                    or len(distribution) != len(answer.probabilities)
                    or not math.isclose(sum(distribution.values()), 1, abs_tol=1e-5)
                ):
                    message = "Decision choice mismatch"
                    raise DecisionError(message)
                choices[answer.name] = Selection(answer.choice, answer.confidence, distribution)
            else:
                message = "Decision answer type mismatch"
                raise DecisionError(message)
        return Decision(probabilities, result.usage.input_tokens, choices, tuple(refused))

    async def aclose(self) -> None:
        await self._http.aclose()
