"""Packaged instructions for the bounded worker planner."""

from functools import cache
from importlib.resources import files


@cache
def worker_prompt(*, web_search: bool = False, mcp: bool = False) -> str:
    """Select the prompt matching the server-owned tool registry."""
    suffix = "-web" if web_search else ""
    text = (
        files(__package__)
        .joinpath(f"worker{suffix}.md")
        .read_text(encoding="utf-8")
        .removesuffix("\n")
    )
    if mcp:
        text += " " + files(__package__).joinpath("mcp.md").read_text(encoding="utf-8").strip()
    return text
