"""Shared classification contracts; transport ownership stays with the application."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Predicate:
    name: str
    instructions: str


@dataclass(frozen=True)
class Option:
    value: str
    description: str = ""


@dataclass(frozen=True)
class Choice:
    name: str
    instructions: str
    choices: tuple[Option, ...]


type Question = Predicate | Choice


@dataclass(frozen=True)
class Selection:
    value: str
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class Decision:
    probabilities: dict[str, float]
    input_tokens: int = 0
    choices: dict[str, Selection] = field(default_factory=dict)
    refused: tuple[str, ...] = ()


class Decider(Protocol):
    async def decide(self, text: str, questions: tuple[Question, ...]) -> Decision: ...

    async def aclose(self) -> None: ...


class DecisionError(Exception):
    """Sanitized unavailable or invalid classification."""


class FakeDecider:
    """Fixed classifications for offline tests; never infer labels from task text."""

    def __init__(
        self, probability: float = 0, *, fail: bool = False, choice: str = "direct"
    ) -> None:
        self.probability, self.fail, self.choice = probability, fail, choice
        self.calls = 0

    async def decide(self, text: str, questions: tuple[Question, ...]) -> Decision:  # noqa: ARG002
        self.calls += 1
        if self.fail:
            message = "Decision unavailable"
            raise DecisionError(message)
        return Decision(
            {q.name: self.probability for q in questions if isinstance(q, Predicate)},
            choices={
                q.name: Selection(
                    self.choice, 1, {o.value: float(o.value == self.choice) for o in q.choices}
                )
                for q in questions
                if isinstance(q, Choice)
            },
        )

    async def aclose(self) -> None:
        pass
