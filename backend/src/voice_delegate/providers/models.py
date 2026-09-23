"""Provider-independent values exchanged with the session manager."""

from dataclasses import dataclass
from typing import Literal

COMMENTARY_MAX_BYTES = 500


class ProviderError(Exception):
    """A sanitized provider failure suitable for application handling."""


class UnsupportedCapability(ProviderError):
    """The selected provider does not expose the requested capability."""


@dataclass(frozen=True)
class ProviderCapabilities:
    """Make transport differences explicit instead of silently ignoring them."""

    ephemeral_credentials: bool = False
    server_control: bool = True
    client_delegation: bool = True
    text_replay: bool = False
    transcript_timing: bool = False


@dataclass(frozen=True)
class SessionConfig:
    """Trusted startup configuration; browser input cannot override it."""

    model: str
    voice: str
    instructions: str
    history: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class WebRTCAnswer:
    """Opaque provider identity and negotiated answer."""

    session_id: str
    sdp: str


@dataclass(frozen=True)
class ClientCredential:
    """Short-lived credentials for providers that support direct setup."""

    value: str
    expires_at: int


@dataclass(frozen=True)
class Transcript:
    """A fragment, not necessarily a complete conversational turn."""

    speaker: Literal["user", "assistant"]
    text: str
    start_ms: float
    end_ms: float
    committed: bool = False


@dataclass(frozen=True)
class DelegationRequested:
    """A request identifier; the application supplies the task context."""

    delegation_id: str
    offset_ms: float = 0
    goal: str = ""


@dataclass(frozen=True)
class SpeechStarted:
    """The provider detected the beginning of user speech."""


@dataclass(frozen=True)
class SessionClosed:
    """Confirmed upstream finalization."""

    reason: str


@dataclass(frozen=True)
class SessionStarted:
    """The provider has started processing the live session."""


@dataclass(frozen=True)
class ProviderFailure:
    """Redacted provider error, without request bodies or credentials."""

    code: str = "provider_error"


type ProviderEvent = (
    Transcript
    | DelegationRequested
    | SpeechStarted
    | SessionClosed
    | SessionStarted
    | ProviderFailure
)


@dataclass(frozen=True)
class Commentary:
    """A compact result associated with a specific delegation."""

    delegation_id: str
    content: str


type ProviderCommand = Commentary
