"""Private Agents bootstrap; SDK media is distinct from server-negotiated SDP."""

import asyncio
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .base import RealtimeConnection
from .models import (
    ClientCredential,
    ProviderCapabilities,
    ProviderError,
    SessionConfig,
    UnsupportedCapability,
)

MAX_RESPONSE_BYTES = 32768


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    token: str = Field(min_length=1, max_length=16000, pattern=r"^\S+$", repr=False)
    conversation_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")


@dataclass(frozen=True)
class BrowserBootstrap:
    """Short-lived SDK credential, not an API key or SDP answer."""

    conversation_id: str
    token: str = field(repr=False)
    transport: str = "elevenlabs_agents_webrtc"


class ElevenLabsProvider:
    """Opt-in Agents adapter; unsupported media/control paths fail explicitly."""

    def __init__(
        self,
        api_key: str,
        agent_id: str,
        *,
        timeout: float = 3,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key or not agent_id or not 0 < timeout <= 5:
            message = "ElevenLabs requires server credentials and a bounded timeout"
            raise ValueError(message)
        self.agent_id = agent_id
        self.timeout = timeout
        self._api_key = api_key
        self.http = http or httpx.AsyncClient(trust_env=False, timeout=timeout)

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(server_control=False, client_delegation=True)

    def default_config(
        self, instructions: str, history: tuple[tuple[str, str], ...] = ()
    ) -> SessionConfig:
        return SessionConfig(self.agent_id, "agent-configured", instructions, history)

    async def _fetch_bootstrap(self) -> BrowserBootstrap:
        raw = bytearray()
        async with asyncio.timeout(self.timeout):
            async with self.http.stream(
                "GET",
                "https://api.elevenlabs.io/v1/convai/conversation/token",
                params={"agent_id": self.agent_id},
                headers={"xi-api-key": self._api_key},
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        message = "ElevenLabs bootstrap exceeds the response budget"
                        raise ValueError(message)
        payload = TokenResponse.model_validate_json(raw)
        return BrowserBootstrap(payload.conversation_id, payload.token)

    async def prepare_browser(self) -> BrowserBootstrap:
        """Mint once; no retry after an ambiguous credential request."""
        try:
            return await self._fetch_bootstrap()
        except (httpx.HTTPError, TimeoutError, ValueError):
            message = "ElevenLabs session setup unavailable"
            raise ProviderError(message) from None

    async def issue_client_credential(self, config: SessionConfig) -> ClientCredential:  # noqa: ARG002 - provider contract
        message = "Agents uses typed browser bootstrap; no credential expiry is assumed"
        raise UnsupportedCapability(message)

    async def connect(self, *, config: SessionConfig, offer_sdp: str) -> RealtimeConnection:  # noqa: ARG002 - provider contract
        message = "ElevenLabs Agents requires SDK-managed WebRTC; SDP setup is unsupported"
        raise UnsupportedCapability(message)

    async def aclose(self) -> None:
        await self.http.aclose()
