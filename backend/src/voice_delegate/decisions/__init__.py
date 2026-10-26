"""Typed, bounded classification; uncertainty never implies cancellation."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Predicate:
    name: str
    instructions: str


@dataclass(frozen=True)
class Decision:
    probabilities: dict[str, float]
    input_tokens: int = 0


class Decider(Protocol):
    async def decide(self, text: str, questions: tuple[Predicate, ...]) -> Decision: ...

    async def aclose(self) -> None: ...


class DecisionError(Exception):
    """Sanitized unavailable or invalid classification."""


class FakeDecider:
    """Deterministic offline classifier; never inspects or logs conversation content."""

    def __init__(self, probability: float = 0, *, fail: bool = False) -> None:
        self.probability = probability
        self.fail = fail
        self.calls = 0

    async def decide(self, text: str, questions: tuple[Predicate, ...]) -> Decision:  # noqa: ARG002
        self.calls += 1
        if self.fail:
            message = "Decision unavailable"
            raise DecisionError(message)
        return Decision(dict.fromkeys((q.name for q in questions), self.probability))

    async def aclose(self) -> None:
        pass
