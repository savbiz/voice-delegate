"""Read-only retrieval from a reviewed bundled corpus; no URL fetching or model claims."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

from langchain_core.tools import tool


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
    if not query.strip() or len(query) > 500:
        return ()
    words = terms(query)
    ranked = []
    for source in corpus():
        body = terms(source.text)
        score = len(words & body) * 3 + len(words & terms(source.section))
        if words & body:
            ranked.append((score, source))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return tuple(source for _, source in ranked[:3])


@tool
def search_documentation(query: str) -> str:
    """Search public project documentation for evidence and citations; max 500 characters."""
    matches = search(query)
    return json.dumps(
        {
            "sources": [{"id": s.id, "text": s.text[:400]} for s in matches],
            "status": "found" if matches else "No supporting documentation found.",
        }
    )
