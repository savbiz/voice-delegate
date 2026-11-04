"""Voice instructions composed from packaged blocks, selected only by trusted settings.

Each block in ``blocks/`` states one rule set once, so a correction applies to every mode:

- ``classic``: delegated work may be cancelled by speech (intent cancellation off).
- ``intent``: speech never cancels work; only the Cancel button does.
- ``semantic``: intent mode plus Decisions-based spoken cancellation.
"""

from functools import cache
from importlib.resources import files
from typing import Literal

Mode = Literal["classic", "intent", "semantic"]


@cache
def block(name: str) -> str:
    return files(__package__).joinpath("blocks", f"{name}.md").read_text(encoding="utf-8").strip()


def blocks_for(mode: Mode, *, web_search: bool) -> tuple[str, ...]:
    """Block names in prompt order for one capability set."""
    names = ["core", "tools-web" if web_search else "tools-offline", "results"]
    if mode != "classic":
        names += ["lifecycle", "cancel-semantic" if mode == "semantic" else "cancel-button"]
        names.append("context")
    names.append("speech")
    return tuple(names)


def mode_for(*, intent_cancellation: bool, decisions_cancel: bool) -> Mode:
    if not intent_cancellation:
        return "classic"
    return "semantic" if decisions_cancel else "intent"


@cache
def voice_prompt(
    *, web_search: bool = False, intent_cancellation: bool = False, decisions_cancel: bool = False
) -> str:
    """Compose the complete system prompt for the enabled capabilities."""
    mode = mode_for(intent_cancellation=intent_cancellation, decisions_cancel=decisions_cancel)
    return "\n\n".join(block(name) for name in blocks_for(mode, web_search=web_search))
