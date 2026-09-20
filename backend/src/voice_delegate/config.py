"""Load validated server settings without exposing credentials to clients."""

from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Resource budgets and server-owned provider configuration."""

    model_config = SettingsConfigDict(env_prefix="VOICE_", extra="ignore")
    openai_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENAI_API_KEY")
    model: str = "gpt-live-1"
    voice: str = "marin"
    allowed_origin: str = "http://localhost:5173"
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    environment: str = "development"
    access_token: SecretStr = SecretStr("")
    otel_enabled: bool = False
    otel_endpoint: str = ""
    max_sessions: int = Field(default=4, ge=1, le=100)
    session_ttl_seconds: float = Field(default=300, gt=0, le=3600)
    heartbeat_timeout_seconds: float = Field(default=45, gt=0)
    connect_timeout_seconds: float = Field(default=20, gt=0)
    close_timeout_seconds: float = Field(default=5, gt=0)
    max_body_bytes: int = Field(default=65536, ge=1024, le=1048576)

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        """Require an explicit browser origin and access gate on public deployments."""
        if self.environment == "production":
            if len(self.access_token.get_secret_value()) < 24:
                raise ValueError("Production requires VOICE_ACCESS_TOKEN of at least 24 characters")
            if not self.allowed_origin.startswith("https://"):
                raise ValueError("Production requires an HTTPS frontend origin")
        return self


def load_settings() -> Settings:
    """Read a local .env without overriding the process environment."""
    load_dotenv(override=False)
    return Settings()
