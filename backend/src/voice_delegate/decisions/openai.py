"""Decisions HTTP contract, verified against the public reference on 2026-10-24."""

import asyncio
from dataclasses import asdict
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import Decision, DecisionError, Predicate


class Answer(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    type: Literal["predicate", "refusal"]
    name: str
    probability: float | None = Field(default=None, ge=0, le=1)


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

    async def decide(self, text: str, questions: tuple[Predicate, ...]) -> Decision:
        if (
            len(text.encode()) > 32768
            or not 1 <= len(questions) <= 4
            or len({q.name for q in questions}) != len(questions)
        ):
            message = "Decision input exceeds budget"
            raise DecisionError(message)
        body = {
            "model": "gpt-6-luna",
            "input": text,
            "questions": [{"type": "predicate", **asdict(q)} for q in questions],
        }
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
        return Decision(
            {
                a.name: a.probability
                for a in result.answers
                if a.type == "predicate" and a.probability is not None
            },
            result.usage.input_tokens,
        )

    async def aclose(self) -> None:
        await self._http.aclose()
