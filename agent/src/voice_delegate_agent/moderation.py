"""Origin-aware moderation contract shared by the worker and its application adapters.

A classifier supplies advisory probabilities; the policy below turns them into one of three
outcomes. Classification cannot prove content safe, so an unavailable or over-budget review
never silently allows external evidence.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

logger = logging.getLogger(__name__)


class Origin(StrEnum):
    """Who authored the text. Instructions inside evidence are data, not requests."""

    USER = "user"
    DOCUMENTATION = "documentation"
    WEB = "web"
    MCP = "mcp"


class Action(StrEnum):
    ALLOW = "allow"
    QUARANTINE = "quarantine"
    REFUSE = "refuse"


class Reason(StrEnum):
    """Fixed labels; the only moderation detail that reaches telemetry."""

    OK = "ok"
    INSTRUCTION_LIKE = "instruction_like"
    UNSUITABLE = "unsuitable"
    UNAVAILABLE = "unavailable"
    BUDGET = "budget"
    OVERSIZE = "oversize"


@dataclass(frozen=True)
class Verdict:
    action: Action
    reason: Reason

    @property
    def allowed(self) -> bool:
        return self.action is Action.ALLOW


@dataclass(frozen=True)
class Signals:
    """Advisory classifier output, each a probability between zero and one."""

    instruction: float
    unsuitable: float


class ModerationUnavailable(Exception):
    """Classification failed, timed out or returned an invalid answer."""


class Classifier(Protocol):
    async def classify(self, origin: Origin, text: str) -> Signals: ...

    async def aclose(self) -> None: ...


class Moderator(Protocol):
    async def review(self, origin: Origin, text: str) -> Verdict:
        """Return a verdict for bounded text; never raise for classifier failures."""
        ...


def failure_verdict(origin: Origin, reason: Reason) -> Verdict:
    """External evidence is withheld; a user request is declined with a reason."""
    return Verdict(Action.REFUSE if origin is Origin.USER else Action.QUARANTINE, reason)


class PolicyModerator:
    """Deterministic policy over advisory signals.

    User requests are refused only when unsuitable: an imperative request is not an
    injection. Evidence is quarantined when it reads as instructions to the assistant or is
    unsuitable. Oversize text and classifier failures never reach the planner.
    """

    def __init__(
        self,
        classifier: Classifier,
        *,
        threshold: float = 0.8,
        max_bytes: int = 16384,
        on_review: Callable[[Origin, Verdict], None] | None = None,
    ) -> None:
        if not 0.5 <= threshold <= 1 or not 1 <= max_bytes <= 32768:
            message = "Invalid moderation threshold or input budget"
            raise ValueError(message)
        self.classifier, self.threshold, self.max_bytes = classifier, threshold, max_bytes
        self.on_review = on_review

    async def review(self, origin: Origin, text: str) -> Verdict:
        verdict = await self._review(origin, text)
        if self.on_review is not None:
            self.on_review(origin, verdict)
        return verdict

    async def _review(self, origin: Origin, text: str) -> Verdict:
        if len(text.encode()) > self.max_bytes:
            return failure_verdict(origin, Reason.OVERSIZE)
        try:
            signals = await self.classifier.classify(origin, text)
        except Exception as error:  # classifier faults of any kind fail closed
            logger.warning(
                "Moderation classifier unavailable (%s); failing closed", type(error).__name__
            )
            return failure_verdict(origin, Reason.UNAVAILABLE)
        if signals.unsuitable >= self.threshold:
            return Verdict(
                Action.REFUSE if origin is Origin.USER else Action.QUARANTINE, Reason.UNSUITABLE
            )
        if origin is not Origin.USER and signals.instruction >= self.threshold:
            return Verdict(Action.QUARANTINE, Reason.INSTRUCTION_LIKE)
        return Verdict(Action.ALLOW, Reason.OK)


class FakeClassifier:
    """Fixed signals for offline tests; never infers labels from the text."""

    def __init__(
        self, instruction: float = 0, unsuitable: float = 0, *, fail: bool = False
    ) -> None:
        self.signals, self.fail = Signals(instruction, unsuitable), fail
        self.calls = 0

    async def classify(self, origin: Origin, text: str) -> Signals:  # noqa: ARG002
        self.calls += 1
        if self.fail:
            message = "Moderation unavailable"
            raise ModerationUnavailable(message)
        return self.signals

    async def aclose(self) -> None:
        pass
