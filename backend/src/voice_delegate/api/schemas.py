"""Validated browser-facing contracts, separate from provider wire formats."""

from dataclasses import replace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from voice_delegate_agent.limits import SOURCE_PREVIEW_CHARS
from voice_delegate_agent.reference import Source

from voice_delegate.session.summary import Recap


class Offer(BaseModel):
    """Only SDP is accepted; models and prompts are server-owned."""

    model_config = ConfigDict(extra="forbid")
    sdp: str = Field(min_length=1, max_length=64000)

    @field_validator("sdp")
    @classmethod
    def validate_sdp(cls, value: str) -> str:
        """Reject obviously invalid input before a billable request."""
        if not value.startswith("v=0") or "\n" not in value:
            message = "Expected an SDP offer"
            raise ValueError(message)
        return value


class Reconnect(Offer):
    """A new browser peer offer tied to the current transport generation."""

    generation: int = Field(ge=0)


class Created(BaseModel):
    """An application session and per-session capability key."""

    id: str
    key: str
    ttl_seconds: float


class Answer(BaseModel):
    """The SDP answer; upstream identities stay server-side."""

    sdp: str


class TaskStatus(BaseModel):
    """Bounded task information, returned only to the session owner."""

    id: str
    goal: str
    status: str
    elapsed_seconds: float
    work_seconds: float = 0
    delivery_wait_seconds: float = 0


class Activity(BaseModel):
    """Fresh, ordered audio activity from the current browser transport."""

    model_config = ConfigDict(extra="forbid", strict=True)
    generation: int = Field(ge=0)
    sequence: int = Field(ge=0, le=1000000)
    user_speaking: bool
    assistant_speaking: bool


class Cancellation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str | None = Field(default=None, min_length=1, max_length=256)


class Status(BaseModel):
    """Transport status; browser session.started confirms actual voice readiness."""

    state: Literal["created", "connecting", "connected", "reconnecting", "closing", "closed"]
    delegation: str = "idle"
    tasks: list[TaskStatus] = Field(default_factory=list)
    decision_cost_usd: float = 0
    generation: int = 0
    fallback_available: bool = False
    sources: tuple[Source, ...] = ()
    recap: Recap = Field(default_factory=Recap)

    @field_validator("sources")
    @classmethod
    def bound_source_text(cls, sources: tuple[Source, ...]) -> tuple[Source, ...]:
        return tuple(replace(source, text=source.text[:SOURCE_PREVIEW_CHARS]) for source in sources)


class Closed(BaseModel):
    """Whether provider finalization was confirmed before cleanup."""

    finalized: bool


class AudioTiming(BaseModel):
    """Bounded, untrusted browser measurements with no conversation content."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["setup", "turn"]
    seconds: float = Field(ge=0, le=120)
    generation: int = Field(ge=0)
