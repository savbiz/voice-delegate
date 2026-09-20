"""Load validated server settings without exposing credentials to clients."""

from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Resource budgets and server-owned provider configuration."""

    model_config = SettingsConfigDict(
        env_prefix="VOICE_", extra="ignore", hide_input_in_errors=True
    )
    openai_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENAI_API_KEY")
    azure_endpoint: str = ""
    azure_api_key: SecretStr = SecretStr("")
    azure_deployment: str = "gpt-realtime"
    azure_voice: str = "marin"
    fallback_enabled: bool = False
    model: str = "gpt-live-1"
    voice: str = "marin"
    allowed_origin: str = "http://localhost:5173"
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    environment: str = "development"
    access_token: SecretStr = SecretStr("")
    invite_tokens: dict[str, SecretStr] = Field(default_factory=dict, repr=False)
    public_demo: bool = False
    demo_enabled: bool = True
    quota_database: str = ".local/quotas.sqlite3"
    daily_sessions_per_user: int = Field(default=4, ge=1, le=100)
    concurrent_sessions_per_user: int = Field(default=1, ge=1, le=10)
    daily_voice_seconds_per_user: int = Field(default=1500, ge=1)
    daily_voice_seconds_global: int = Field(default=6000, ge=1)
    max_delegations_per_session: int = Field(default=8, ge=1, le=64)
    otel_enabled: bool = False
    otel_endpoint: str = ""
    otel_metrics_endpoint: str = ""
    worker_mode: Literal["offline", "openai"] = "offline"
    worker_model: str = "gpt-4.1-mini"
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
    def validate_production(self) -> "Settings":
        """Require an explicit browser origin and access gate on public deployments."""
        if len(self.invite_tokens) > 100:
            raise ValueError("At most 100 named invitations are supported")
        values = [token.get_secret_value() for token in self.invite_tokens.values()]
        if any(not name or len(name) > 64 for name in self.invite_tokens):
            raise ValueError("Invitation names must contain 1 to 64 characters")
        if any(len(value) < 32 for value in values) or len(set(values)) != len(values):
            raise ValueError("Invitations require unique random tokens of at least 32 characters")
        if self.public_demo and (not values or self.quota_database == ":memory:"):
            raise ValueError("Public demo requires named invitations and durable quota storage")
        if self.public_demo and self.environment != "production":
            raise ValueError("Public demo requires production configuration")
        if self.fallback_enabled:
            from urllib.parse import urlparse

            endpoint = urlparse(self.azure_endpoint)
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or not endpoint.hostname.endswith(".openai.azure.com")
                or endpoint.path not in {"", "/"}
                or endpoint.query
                or endpoint.fragment
                or endpoint.username
                or endpoint.password
                or endpoint.port not in {None, 443}
            ):
                raise ValueError("Azure endpoint must be an HTTPS Azure OpenAI resource origin")
            if not self.azure_api_key.get_secret_value():
                raise ValueError("Azure fallback requires VOICE_AZURE_API_KEY")
        if self.worker_mode == "openai" and not self.openai_api_key.get_secret_value():
            raise ValueError("VOICE_WORKER_MODE=openai requires OPENAI_API_KEY")
        if self.environment == "production":
            if not self.invite_tokens and len(self.access_token.get_secret_value()) < 24:
                raise ValueError("Production requires VOICE_ACCESS_TOKEN of at least 24 characters")
            if not self.allowed_origin.startswith("https://"):
                raise ValueError("Production requires an HTTPS frontend origin")
        return self


def load_settings() -> Settings:
    """Read a local .env without overriding the process environment."""
    load_dotenv(override=False)
    return Settings()
