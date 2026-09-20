"""Read-only retrieval from a reviewed bundled corpus; no URL fetching or model claims."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Self

from langchain_core.tools import tool


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    path: str
    section: str
    text: str
    digest: str


class GroundedAnswer(str):
    """Text remains compatible with worker contracts; citations travel out of band."""

    sources: tuple[Source, ...]

    def __new__(cls, text: str, sources: tuple[Source, ...]) -> Self:
        answer = super().__new__(cls, text)
        answer.sources = sources
        return answer


@lru_cache(maxsize=1)
def corpus() -> tuple[Source, ...]:
    payload = files("voice_delegate_agent").joinpath("data/reference.json").read_text()
    return tuple(Source(**entry) for entry in json.loads(payload))


def source_by_id(source_id: str) -> Source | None:
    return next((source for source in corpus() if source.id == source_id), None)


STOP = set(
    "the a an and or to of is are in on for how what does do this project it with "
    "come cosa che il la le lo gli un una di del della per e è i si nel quali".split()
)
ALIASES = {
    "interruzione": "interruption",
    "interruzioni": "interruptions",
    "cancellazione": "cancellation",
    "limiti": "limits",
    "quote": "quotas",
    "sessione": "session",
    "sessioni": "sessions",
    "cronologia": "history",
    "voce": "voice",
    "sicurezza": "authentication",
    "fonti": "sources",
    "scadenza": "timeout",
    "delegazione": "delegation",
    "architettura": "architecture",
    "replayed": "replay",
    "replays": "replay",
}


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
    if "history" in words:
        words.update({"replay", "sealed"})
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
