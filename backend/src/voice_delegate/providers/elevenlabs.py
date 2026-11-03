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


def _headers(value: Any) -> dict[str, Any]:
    """Normalize API maps and dashboard lists without hiding duplicate headers."""
    if isinstance(value, list):
        normalized = {}
        for item in value:
            _require(isinstance(item, dict))
            kind = item.get("type")
            field = {"secret": "secret_id", "dynamic_variable": "variable_name"}.get(kind)
            _require(field is not None)
            _require(set(item) == {"type", "name", field})
            name = item["name"]
            _require(isinstance(name, str) and name.lower() not in normalized)
            normalized[name.lower()] = {field: item[field]}
        return normalized
    _require(isinstance(value, dict))
    _require(all(isinstance(name, str) for name in value))
    normalized = {name.lower(): item for name, item in value.items()}
    _require(len(normalized) == len(value))
    return normalized


def _goal_parameter(parameters: Any) -> dict[str, Any]:
    """Accept the dashboard property schema and the JSON Schema API representation."""
    _require(isinstance(parameters, dict) and parameters.get("type") == "object")
    _require(
        not parameters.get("dynamic_variable")
        and not parameters.get("constant_value")
        and not parameters.get("is_omitted")
        and parameters.get("value_type", "llm_prompt") == "llm_prompt"
    )
    properties = parameters["properties"]
    if isinstance(properties, list):
        _require(len(properties) == 1 and isinstance(properties[0], dict))
        goal = properties[0]
        _require(goal.get("id") == "goal" and goal.get("required") is True)
        _require(isinstance(parameters.get("required", False), bool))
    else:
        _require(isinstance(properties, dict) and set(properties) == {"goal"})
        _require(parameters["required"] == ["goal"])
        goal = properties["goal"]
    _require(isinstance(goal, dict))
    _require(goal.get("value_type", "llm_prompt") == "llm_prompt")
    return dict(goal)


def _workflow_inactive(value: Any) -> bool:
    """Allow only absent workflows or the dashboard's isolated start placeholder."""
    if value is None or value == {}:
        return True
    if not isinstance(value, dict):
        return False
    if set(value) - {"nodes", "edges", "subgraphs", "prevent_subagent_loops"}:
        return False
    if value.get("edges") or value.get("subgraphs"):
        return False
    if value.get("prevent_subagent_loops", False) is not False:
        return False
    nodes = value.get("nodes", {})
    if not isinstance(nodes, dict) or len(nodes) > 1:
        return False
    if not nodes:
        return True
    node = next(iter(nodes.values()))
    return (
        isinstance(node, dict)
        and not set(node) - {"type", "position", "edge_order", "parent_subgraph_id"}
        and node.get("type") == "start"
        and not node.get("edge_order")
        and node.get("parent_subgraph_id") is None
    )


def _validate_webhook(tool: Any, webhook_url: str) -> dict[str, Any]:
    """Validate each advertised tool representation against the same policy."""
    _require(tool["type"] == "webhook" and tool["name"] == "delegate_task")
    _require(tool["execution_mode"] == "async")
    _require(tool.get("interruption_mode", "allow") == "allow")
    _require(tool["response_timeout_secs"] == 120)
    _require(tool.get("follow_redirects", False) is False)
    schema = tool["api_schema"]
    _require(bool(webhook_url) and schema["url"] == webhook_url)
    _require(schema["method"] == "POST")
    _require(schema.get("content_type") in (None, "application/json"))
    _require(not schema.get("path_params_schema"))
    _require(not schema.get("query_params_schema"))
    _require(not schema.get("auth_connection"))
    _require(not schema.get("mtls_auth_connection"))
    _require(not schema.get("response_filter"))
    headers = _headers(schema["request_headers"])
    _require(set(headers) == {"x-voice-webhook-token", "x-voice-conversation-id"})
    token = headers["x-voice-webhook-token"]
    _require(
        isinstance(token, dict)
        and set(token) == {"secret_id"}
        and isinstance(token["secret_id"], str)
        and bool(token["secret_id"])
    )
    _require(headers["x-voice-conversation-id"] == {"variable_name": "system__conversation_id"})
    goal = _goal_parameter(schema["request_body_schema"])
    _require(goal["type"] == "string" and bool(goal.get("description")))
    _require(
        not any(
            goal.get(k)
            for k in (
                "dynamic_variable",
                "constant_value",
                "is_system_provided",
                "is_omitted",
            )
        )
    )
    return headers


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
        webhook_url: str = "",
    ) -> None:
        if not api_key or not agent_id or not 0 < timeout <= 5:
            message = "ElevenLabs requires server credentials and a bounded timeout"
            raise ValueError(message)
        self.webhook_url = webhook_url
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
                _require(_workflow_inactive(agent.get("workflow")))
                _require(_overrides_disabled(platform.get("overrides", {})))
                conversation = config["conversation"]
                _require(0 < conversation["max_duration_seconds"] <= ttl)
                prompt = config["agent"]["prompt"]
                builtins = prompt.get("built_in_tools")
                _require(
                    builtins is None
                    or (
                        isinstance(builtins, dict)
                        and all(value is None for value in builtins.values())
                    )
                )
                tools = prompt.get("tools", [])
                identities = prompt.get("tool_ids", [])
                _require(isinstance(tools, list) and len(tools) <= 1)
                _require(isinstance(identities, list) and len(identities) <= 1)
                if identities:
                    identity = identities[0]
                    _require(
                        isinstance(identity, str)
                        and re.fullmatch("[a-zA-Z0-9_-]{1,200}", identity) is not None
                    )
                    tools = [*tools, (await self._json("tools/" + identity))["tool_config"]]
                _require(bool(tools))
                headers = [_validate_webhook(tool, self.webhook_url) for tool in tools]
                _require(all(value == headers[0] for value in headers))
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
                "ElevenLabs agent requires private async webhook delegate_task "
                "and a bounded call lifetime"
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
