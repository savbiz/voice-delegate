"""Load validated server settings without exposing credentials to clients."""

from ipaddress import ip_address, ip_network
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource, EnvSettingsSource
from voice_delegate_agent.model_config import DEFAULT_WORKER_MODEL
from voice_delegate_agent.web_search import domain_name

from voice_delegate.limits.defaults import WORKER_PORT


def azure_origin_allowed(url: str) -> bool:
    """Accept only an HTTPS Azure OpenAI resource origin, never a path, port or credentials."""
    try:
        target = urlsplit(url)
        port = target.port
    except ValueError:
        return False
    return not (
        target.scheme != "https"
        or not target.hostname
        or not target.hostname.endswith(".openai.azure.com")
        or target.path not in {"", "/"}
        or target.query
        or target.fragment
        or target.username
        or target.password
        or port not in {None, 443}
    )


def worker_transport_allowed(url: str) -> bool:
    """Permit plaintext only on loopback, private IPs, the compose worker or Railway hosts."""
    target = urlsplit(url)
    if not target.hostname or target.username or target.password or target.query or target.fragment:
        return False
    if target.scheme == "https":
        return True
    if target.scheme != "http" or not target.hostname:
        return False
    if target.hostname in {"localhost", "worker"} or target.hostname.endswith(".railway.internal"):
        return True
    try:
        address = ip_address(target.hostname)
    except ValueError:
        return False
    return address.is_loopback or any(
        address in ip_network(network)
        for network in (
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "fc00::/7",
        )
    )


class Settings(BaseSettings):
    """Resource budgets and server-owned provider configuration."""

    model_config = SettingsConfigDict(
        env_prefix="VOICE_", extra="ignore", hide_input_in_errors=True, populate_by_name=True
    )
    openai_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENAI_API_KEY")
    azure_endpoint: str = ""
    azure_api_key: SecretStr = SecretStr("")
    azure_deployment: str = "gpt-live-1"
    azure_voice: str = "marin"
    fallback_enabled: bool = False
    voice_provider: Literal["openai", "azure", "elevenlabs"] = Field(
        default="openai",
        validation_alias=AliasChoices("VOICE_ADAPTER", "VOICE_VOICE_PROVIDER"),
        description="Voice adapter. VOICE_VOICE_PROVIDER is a deprecated alias.",
    )

    @field_validator("voice_provider", mode="before")
    @classmethod
    def canonical_adapter(cls, value: object) -> object:
        return "openai" if value in ("live", "realtime") else value

    elevenlabs_enabled: bool = False
    elevenlabs_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="ELEVENLABS_API_KEY"
    )
    elevenlabs_agent_id: str = Field(
        default="", max_length=200, pattern=r"^(agent_[a-zA-Z0-9_-]+)?$"
    )
    elevenlabs_timeout_seconds: float = Field(default=3, gt=0, le=5)
    elevenlabs_webhook_token: SecretStr = SecretStr("")
    elevenlabs_webhook_url: str = ""
    model: str = "gpt-live-1"
    voice: str = "marin"
    native_clients: bool = False
    allowed_origins: list[str] = Field(default=["http://localhost:5173"], min_length=1)
    allowed_origin: str | None = Field(
        default=None, description="Deprecated: use VOICE_ALLOWED_ORIGINS"
    )
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    trust_proxy: bool = False
    trusted_proxy_hops: int = Field(default=1, ge=1, le=32)
    environment: str = "development"
    api_docs: bool = False
    session_ui: bool = False
    cost_estimates: bool = True
    price_file: str = ""
    audio_timing: bool = False
    intent_cancellation: bool = False
    max_inflight_tasks: int = Field(default=2, ge=1, le=2)
    delivery_timeout_seconds: float = Field(default=30, gt=0, le=120)
    delivery_silence_seconds: float = Field(default=0.6, ge=0.3, le=5)
    delivery_preamble: str = Field(default="About your request", min_length=1, max_length=80)
    decisions_cancel: bool = False
    decisions_threshold: float = Field(default=0.85, ge=0.5, le=1)
    decisions_timeout_seconds: float = Field(default=1, gt=0, le=5)
    decisions_max_calls: int = Field(default=60, ge=1, le=300)
    decisions_input_usd_per_million: float = Field(default=0.1, ge=0, le=100)
    debug_recording: bool = False
    debug_directory: str = ".local/debug"
    access_token: SecretStr = SecretStr("")
    invite_tokens: dict[str, SecretStr] = Field(default_factory=dict, repr=False)
    public_demo: bool = False
    demo_enabled: bool = True
    quota_database: str = ".local/quotas.sqlite3"
    feedback_database: str = ".local/feedback.sqlite3"
    daily_sessions_per_user: int = Field(default=4, ge=1, le=100)
    concurrent_sessions_per_user: int = Field(default=1, ge=1, le=10)
    daily_voice_seconds_per_user: int = Field(default=1500, ge=1)
    daily_voice_seconds_global: int = Field(default=6000, ge=1)
    max_delegations_per_session: int = Field(default=8, ge=1, le=64)
    otel_enabled: bool = False
    otel_endpoint: str = ""
    otel_metrics_endpoint: str = ""
    instance_id: str = Field(default="", pattern=r"^[a-z0-9]{0,16}$")
    worker_execution: Literal["local", "remote"] = "local"
    # http:// worker URLs are only acceptable on the same host or a private network.
    worker_service_url: str = f"http://worker:{WORKER_PORT}"
    worker_service_token: SecretStr = SecretStr("")
    worker_service_capacity: int = Field(default=4, ge=1, le=32)
    worker_max_records: int = Field(default=128, ge=32, le=1024)
    worker_mode: Literal["offline", "openai", "decisions"] = "offline"
    web_search: bool = False
    tavily_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="TAVILY_API_KEY")
    web_search_domains: list[str] = Field(default_factory=list, max_length=20)
    web_search_timeout_seconds: float = Field(default=3, gt=0, le=5)
    worker_model: str = DEFAULT_WORKER_MODEL
    delegation_timeout_seconds: float = Field(default=15, gt=0, le=120)
    delegation_result_tokens: int = Field(default=120, ge=8, le=480)
    worker_max_steps: int = Field(default=4, ge=1, le=12)
    max_sessions: int = Field(default=4, ge=1, le=100)
    session_ttl_seconds: float = Field(default=300, gt=0, le=3600)
    heartbeat_timeout_seconds: float = Field(default=45, gt=0)
    connect_timeout_seconds: float = Field(default=20, gt=0)
    close_timeout_seconds: float = Field(default=5, gt=0)
    max_body_bytes: int = Field(default=65536, ge=1024, le=1048576)

    @model_validator(mode="after")
    def validate_elevenlabs(self) -> "Settings":
        if self.voice_provider == "elevenlabs" and not self.elevenlabs_enabled:
            message = "ElevenLabs adapter requires complete backend agent credentials"
            raise ValueError(message)
        if self.elevenlabs_enabled and (
            not self.elevenlabs_api_key.get_secret_value() or not self.elevenlabs_agent_id
        ):
            message = "ElevenLabs requires ELEVENLABS_API_KEY and VOICE_ELEVENLABS_AGENT_ID"
            raise ValueError(message)
        if self.elevenlabs_enabled:
            url = urlsplit(self.elevenlabs_webhook_url)
            if (
                len(self.elevenlabs_webhook_token.get_secret_value()) < 32
                or url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path != "/integrations/elevenlabs/delegate"
            ):
                message = (
                    "ElevenLabs requires a webhook token of at least 32 characters "
                    "and an HTTPS webhook URL"
                )
                raise ValueError(message)
        if self.voice_provider == "elevenlabs" and not self.intent_cancellation:
            message = "ElevenLabs async delegation requires VOICE_INTENT_CANCELLATION"
            raise ValueError(message)
        if self.voice_provider == "elevenlabs" and self.fallback_enabled and not self.session_ui:
            message = "ElevenLabs does not support cross-vendor fallback without session selection"
            raise ValueError(message)
        if (
            self.voice_provider == "elevenlabs"
            and self.delegation_timeout_seconds + self.delivery_timeout_seconds > 110
        ):
            message = "ElevenLabs work and delivery must fit the webhook deadline"
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def validate_web_search(self) -> "Settings":
        self.web_search_domains = list(
            dict.fromkeys(domain_name(value) for value in self.web_search_domains)
        )
        if (
            self.web_search
            and self.worker_execution == "local"
            and not self.tavily_api_key.get_secret_value()
        ):
            message = "Web search requires TAVILY_API_KEY on the worker host"
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def validate_origins(self) -> "Settings":
        """Accept the deprecated singular setting only when no list was supplied."""
        if self.allowed_origin is not None and "allowed_origins" not in self.model_fields_set:
            self.allowed_origins = [self.allowed_origin]
        for origin in self.allowed_origins:
            if self.native_clients and origin == "capacitor://localhost":
                continue
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in parsed.netloc
                or origin != f"{parsed.scheme}://{parsed.netloc}"
                or origin != str(HttpUrl(origin)).removesuffix("/")
            ):
                message = (
                    "Allowed origins must be canonical HTTP(S) origins: "
                    "lowercase hosts, no paths or default ports"
                )
                raise ValueError(message)
        return self

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        """Require an explicit browser origin and access gate on public deployments."""
        if self.decisions_cancel and (
            not self.intent_cancellation or not self.openai_api_key.get_secret_value()
        ):
            message = "Decisions cancellation requires intent cancellation and OPENAI_API_KEY"
            raise ValueError(message)
        if self.instance_id and not self.public_demo:
            message = "Multiple API instances require public-demo identity and quota controls"
            raise ValueError(message)
        if self.worker_execution == "remote":
            from urllib.parse import urlparse

            target = urlparse(self.worker_service_url)
            if (
                target.scheme not in {"http", "https"}
                or not target.hostname
                or target.username
                or target.password
                or target.query
                or target.fragment
            ):
                message = "Worker URL must be an HTTP(S) service origin"
                raise ValueError(message)
            if not worker_transport_allowed(self.worker_service_url):
                message = "Worker requires HTTPS outside private IPs, loopback or compose"
                raise ValueError(message)
            if len(self.worker_service_token.get_secret_value()) < 32:
                message = "Remote worker requires a service token of at least 32 characters"
                raise ValueError(message)
        if len(self.invite_tokens) > 100:
            message = "At most 100 named invitations are supported"
            raise ValueError(message)
        values = [token.get_secret_value() for token in self.invite_tokens.values()]
        if any(not name or len(name) > 64 for name in self.invite_tokens):
            message = "Invitation names must contain 1 to 64 characters"
            raise ValueError(message)
        if any(len(value) < 32 for value in values) or len(set(values)) != len(values):
            message = "Invitations require unique random tokens of at least 32 characters"
            raise ValueError(message)
        if self.public_demo and (not values or self.quota_database == ":memory:"):
            message = "Public demo requires named invitations and durable quota storage"
            raise ValueError(message)
        if self.public_demo and self.environment != "production":
            message = "Public demo requires production configuration"
            raise ValueError(message)
        if (
            self.fallback_enabled
            or self.voice_provider == "azure"
            or (self.session_ui and self.azure_endpoint and self.azure_api_key.get_secret_value())
        ):
            if not azure_origin_allowed(self.azure_endpoint):
                message = "Azure endpoint must be an HTTPS Azure OpenAI resource origin"
                raise ValueError(message)
            if not self.azure_api_key.get_secret_value():
                message = "Azure fallback requires VOICE_AZURE_API_KEY"
                raise ValueError(message)
        if self.fallback_enabled and self.voice_provider == "azure":
            message = "Azure cannot be both primary and fallback"
            raise ValueError(message)
        if self.worker_mode != "offline" and not self.openai_api_key.get_secret_value():
            message = "Paid worker modes require OPENAI_API_KEY"
            raise ValueError(message)
        if self.environment == "production":
            if "testserver" in self.allowed_hosts:
                message = "Production requires explicit VOICE_ALLOWED_HOSTS without testserver"
                raise ValueError(message)
            if not self.invite_tokens and len(self.access_token.get_secret_value()) < 24:
                message = "Production requires VOICE_ACCESS_TOKEN of at least 24 characters"
                raise ValueError(message)
            if any(
                not origin.startswith("https://")
                and not (self.native_clients and origin == "capacitor://localhost")
                for origin in self.allowed_origins
            ):
                message = "Production requires an HTTPS frontend origin"
                raise ValueError(message)
        return self


# Runtime behaviour is automatic. Constructor overrides remain for offline contract tests.
AUTOMATIC_FEATURES = {
    "cost_estimates",
    "session_ui",
    "intent_cancellation",
    "audio_timing",
    "native_clients",
    "elevenlabs_enabled",
    "web_search",
    "fallback_enabled",
    "debug_recording",
    "otel_enabled",
}


def load_settings() -> Settings:
    """Load keys and deployment settings; obsolete feature environment flags are ignored."""
    values = {**DotEnvSettingsSource(Settings, env_file=".env")(), **EnvSettingsSource(Settings)()}
    values.update(
        cost_estimates=True,
        session_ui=True,
        intent_cancellation=True,
        audio_timing=True,
        native_clients=True,
        debug_recording=True,
        otel_enabled=True,
    )
    values["elevenlabs_enabled"] = bool(
        values.get("ELEVENLABS_API_KEY") and values.get("elevenlabs_agent_id")
    )
    values["web_search"] = bool(
        values.get("TAVILY_API_KEY") or values.get("worker_execution") == "remote"
    )
    adapter = values.get("VOICE_ADAPTER", values.get("VOICE_VOICE_PROVIDER", "openai"))
    values["fallback_enabled"] = bool(
        values.get("azure_endpoint") and values.get("azure_api_key") and adapter != "azure"
    )
    if "worker_mode" not in values:
        values["worker_mode"] = "openai" if values.get("OPENAI_API_KEY") else "offline"
    return Settings(**values)
