"""Private Agents bootstrap; SDK media is distinct from server-negotiated SDP."""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

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


def _require(condition: bool) -> None:
    if not condition:
        message = "Unsafe agent configuration"
        raise ValueError(message)


def _overrides_disabled(value: object) -> bool:
    return value is False or (
        isinstance(value, dict) and all(_overrides_disabled(v) for v in value.values())
    )


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

    async def _json(self, path: str) -> dict[str, Any]:
        """Read only fixed provider resources with bounded bodies and no retries."""
        raw = bytearray()
        async with asyncio.timeout(self.timeout):
            async with self.http.stream(
                "GET",
                "https://api.elevenlabs.io/v1/convai/" + path,
                headers={"xi-api-key": self._api_key},
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        message = "Agent configuration exceeds the input budget"
                        raise ValueError(message)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            message = "Invalid agent configuration"
            raise TypeError(message)
        return payload

    async def validate_agent(self, ttl: float) -> None:
        """Fail closed unless the private agent enforces async delegation and lifetime."""
        try:
            async with asyncio.timeout(self.timeout):
                agent = await self._json("agents/" + self.agent_id)
                config = agent["conversation_config"]
                platform = agent["platform_settings"]
                _require(isinstance(config, dict) and isinstance(platform, dict))
                _require(platform["auth"]["enable_auth"] is True)
                _require(not agent.get("workflow"))
                _require(_overrides_disabled(platform.get("overrides", {})))
                conversation = config["conversation"]
                _require(0 < conversation["max_duration_seconds"] <= ttl)
                prompt = config["agent"]["prompt"]
                tools = prompt.get("tools", [])
                identities = prompt.get("tool_ids", [])
                if identities:
                    _require(not tools and len(identities) == 1)
                    identity = identities[0]
                    _require(
                        isinstance(identity, str)
                        and re.fullmatch("[a-zA-Z0-9_-]{1,200}", identity) is not None
                    )
                    tools = [(await self._json("tools/" + identity))["tool_config"]]
                _require(len(tools) == 1)
                tool = tools[0]
                _require(tool["type"] == "client" and tool["name"] == "delegate_task")
                _require(tool["expects_response"] is True and tool["execution_mode"] == "async")
                _require(tool.get("interruption_mode", "allow") == "allow")
                _require(tool["response_timeout_secs"] == 120)
                parameters = tool["parameters"]
                _require(parameters["required"] == ["goal"])
                _require(set(parameters["properties"]) == {"goal"})
                _require(parameters["properties"]["goal"]["type"] == "string")
        except (
            httpx.HTTPError,
            TimeoutError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            IndexError,
        ):
            message = (
                "ElevenLabs agent requires private async delegate_task and a bounded call lifetime"
            )
            raise ProviderError(message) from None

    async def confirm_closed(self, conversation_id: str) -> bool:
        """A browser disconnect alone cannot confirm that upstream usage ended."""
        try:
            payload = await self._json("conversations/" + conversation_id)
            return payload.get("agent_id") == self.agent_id and payload.get("status") in {
                "done",
                "failed",
            }
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError):
            return False

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
