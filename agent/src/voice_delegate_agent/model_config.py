"""Shared worker model defaults and endpoint-specific compatibility settings."""

from typing import Literal

DEFAULT_WORKER_MODEL = "gpt-6-luna"


def chat_reasoning_effort(model: str) -> Literal["none"] | None:
    """Luna tool calling through Chat Completions requires reasoning to be disabled."""
    return "none" if model == "gpt-6-luna" or model.startswith("gpt-6-luna-") else None
