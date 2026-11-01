"""Packaged voice instructions, selected only by trusted server settings."""

from functools import cache
from importlib.resources import files


@cache
def voice_prompt(
    *, web_search: bool = False, intent_cancellation: bool = False, decisions_cancel: bool = False
) -> str:
    """Load the complete system prompt for the enabled capabilities."""
    mode = (
        "semantic"
        if intent_cancellation and decisions_cancel
        else ("intent" if intent_cancellation else "classic")
    )
    suffix = "-web" if web_search else ""
    return (
        files(__package__)
        .joinpath(f"voice-{mode}{suffix}.md")
        .read_text(encoding="utf-8")
        .removesuffix("\n")
    )
