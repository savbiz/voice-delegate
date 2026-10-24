"""Read-only retrieval from a reviewed bundled corpus; no URL fetching or model claims."""

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from langchain_core.tools import tool

from .limits import QUERY_MAX_CHARS, SOURCE_PREVIEW_CHARS


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    path: str
    section: str
    text: str
    digest: str


@dataclass(frozen=True)
class WorkerResult:
    """Worker text and immutable evidence are separate parts of the result."""

    text: str
    sources: tuple[Source, ...] = ()
    status: Literal["completed", "failed"] = "completed"


@lru_cache(maxsize=1)
def corpus() -> tuple[Source, ...]:
    payload = files("voice_delegate_agent").joinpath("data/reference.json").read_text()
    return tuple(Source(**entry) for entry in json.loads(payload))


def source_by_id(source_id: str) -> Source | None:
    return next((source for source in corpus() if source.id == source_id), None)


STOP: set[str] = set(
    json.loads(files("voice_delegate_agent").joinpath("data/stopwords.json").read_text())
)
ALIASES: dict[str, str] = json.loads(
    files("voice_delegate_agent").joinpath("data/aliases.json").read_text()
)


def terms(text: str) -> set[str]:
    return {
        ALIASES.get(word, word)
        for word in re.findall(r"[\w-]+", text.lower())
        if len(word) > 2 and word not in STOP
    }


def search(query: str) -> tuple[Source, ...]:
    if not query.strip() or len(query) > QUERY_MAX_CHARS:
        return ()
    words = terms(query)
    sources = corpus()
    bodies = [
        Counter(
            ALIASES.get(word, word)
            for word in re.findall(r"[\w-]+", source.text.lower())
            if len(word) > 2 and word not in STOP
        )
        for source in sources
    ]
    vocabulary = set().union(*(set(body) for body in bodies))
    # A single generic overlap does not support a mostly out-of-corpus question.
    if len(words) >= 3 and len(words & vocabulary) * 2 < len(words):
        return ()
    ranked: list[tuple[float, Source]] = []
    for source, body in zip(sources, bodies, strict=True):
        # Sublinear repetition rewards focused evidence without letting long sections dominate.
        score = sum(1 + math.log(body[word]) for word in words & body.keys())
        if score:
            ranked.append((score, source))
    if not ranked:
        return tuple(
            source for source in sources if words & (terms(source.title) | terms(source.section))
        )[:3]
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return tuple(source for _, source in ranked[:3])


@tool
def search_documentation(query: str) -> str:
    """Search public project documentation for evidence and citations; max 500 characters."""
    matches = search(query)
    return json.dumps(
        {
            "sources": [{"id": s.id, "text": s.text[:SOURCE_PREVIEW_CHARS]} for s in matches],
            "status": "found" if matches else "No supporting documentation found.",
        }
    )
