"""Bounded personal keys: memory-only request data, excluded from public responses."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from voice_delegate.config import Settings


class PersonalKeys(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    openai_key: SecretStr = Field(default=SecretStr(""), max_length=4096)
    tavily_key: SecretStr = Field(default=SecretStr(""), max_length=4096)
    elevenlabs_key: SecretStr = Field(default=SecretStr(""), max_length=4096)
    elevenlabs_agent_id: str = Field(
        default="", max_length=200, pattern=r"^(agent_[a-zA-Z0-9_-]+)?$"
    )
    elevenlabs_webhook_token: SecretStr = Field(default=SecretStr(""), max_length=4096)
    azure_key: SecretStr = Field(default=SecretStr(""), max_length=4096)
    azure_endpoint: str = Field(default="", max_length=512)
    azure_deployment: str = Field(
        default="gpt-realtime", min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9._-]+$"
    )

    @field_validator(
        "openai_key", "tavily_key", "elevenlabs_key", "azure_key", "elevenlabs_webhook_token"
    )
    @classmethod
    def safe_header_value(cls, value: SecretStr) -> SecretStr:
        if any(not 33 <= ord(character) <= 126 for character in value.get_secret_value()):
            message = "Provider keys must contain printable ASCII without whitespace"
            raise ValueError(message)
        return value

    def worker_settings(self, settings: Settings) -> Settings:
        """Replace every provider key explicitly; never inherit platform billing."""
        return settings.model_copy(
            update={
                "openai_api_key": self.openai_key,
                "tavily_api_key": self.tavily_key,
                "azure_api_key": self.azure_key,
                "azure_endpoint": self.azure_endpoint,
                "azure_deployment": self.azure_deployment,
                "elevenlabs_api_key": self.elevenlabs_key,
                "elevenlabs_agent_id": self.elevenlabs_agent_id,
                "elevenlabs_webhook_token": self.elevenlabs_webhook_token,
                "worker_mode": "openai" if self.openai_key.get_secret_value() else "offline",
                "web_search": bool(self.tavily_key.get_secret_value()),
                "decisions_cancel": False,
            }
        )
