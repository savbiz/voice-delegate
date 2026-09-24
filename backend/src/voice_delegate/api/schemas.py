"""Validated browser-facing contracts, separate from provider wire formats."""

from pydantic import BaseModel, ConfigDict, Field, field_validator
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


class Status(BaseModel):
    """Transport status; browser session.started confirms actual voice readiness."""

    state: str
    delegation: str = "idle"
    generation: int = 0
    fallback_available: bool = False
    sources: tuple[Source, ...] = ()
    recap: Recap = Field(default_factory=Recap)


class Closed(BaseModel):
    """Whether provider finalization was confirmed before cleanup."""

    finalized: bool
