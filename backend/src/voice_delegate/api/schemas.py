"""Validated browser-facing contracts, separate from provider wire formats."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Offer(BaseModel):
    """Only SDP is accepted; models and prompts are server-owned."""

    model_config = ConfigDict(extra="forbid")
    sdp: str = Field(min_length=1, max_length=64000)

    @field_validator("sdp")
    @classmethod
    def validate_sdp(cls, value: str) -> str:
        """Reject obviously invalid input before a billable request."""
        if not value.startswith("v=0") or "\n" not in value:
            raise ValueError("Expected an SDP offer")
        return value


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


class Closed(BaseModel):
    """Whether provider finalization was confirmed before cleanup."""

    finalized: bool
