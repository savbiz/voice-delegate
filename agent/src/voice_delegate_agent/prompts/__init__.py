"""Packaged instructions for the bounded worker planner."""

from functools import cache
from importlib.resources import files


@cache
def worker_prompt(*, web_search: bool = False) -> str:
    """Select the prompt matching the server-owned tool registry."""
    suffix = "-web" if web_search else ""
    return (
        files(__package__)
        .joinpath(f"worker{suffix}.md")
        .read_text(encoding="utf-8")
        .removesuffix("\n")
    )
