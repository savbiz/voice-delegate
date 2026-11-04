"""Numeric usage only; context-local sinks isolate concurrent delegations."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel, ConfigDict, Field


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    worker_calls: int = Field(default=0, ge=0, le=1000000)
    input_tokens: int = Field(default=0, ge=0, le=1000000000)
    cached_tokens: int = Field(default=0, ge=0, le=1000000000)
    output_tokens: int = Field(default=0, ge=0, le=1000000000)
    decision_calls: int = Field(default=0, ge=0, le=1000000)
    decision_tokens: int = Field(default=0, ge=0, le=1000000000)
    web_calls: int = Field(default=0, ge=0, le=1000000)
    mcp_calls: int = Field(default=0, ge=0, le=1000000)
    uncertain: bool = False

    def plus(self, other: Usage) -> Usage:
        return Usage(
            **{
                name: min(
                    getattr(self, name) + getattr(other, name),
                    1000000000 if "tokens" in name else 1000000,
                )
                for name in type(self).model_fields
                if name != "uncertain"
            },
            uncertain=self.uncertain or other.uncertain,
        )


type UsageSink = Callable[[Usage], None]
_sink: ContextVar[UsageSink | None] = ContextVar("usage_sink", default=None)


def note(usage: Usage) -> None:
    sink = _sink.get()
    if sink is not None:
        sink(usage)


@contextmanager
def usage_sink(sink: UsageSink | None) -> Iterator[None]:
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


@contextmanager
def external_call(kind: str) -> Iterator[None]:
    note(Usage.model_validate({kind: 1}))
    try:
        yield
    except BaseException:
        note(Usage(uncertain=True))
        raise


def model_usage(metadata: object) -> None:
    if not isinstance(metadata, dict) or not all(
        isinstance(metadata.get(key), int)
        and not isinstance(metadata[key], bool)
        and 0 <= metadata[key] <= 1000000000
        for key in ("input_tokens", "output_tokens")
    ):
        note(Usage(uncertain=True))
        return
    details = metadata.get("input_token_details")
    cached = details.get("cache_read", 0) if isinstance(details, dict) else 0
    if not isinstance(cached, int) or not 0 <= cached <= metadata["input_tokens"]:
        note(Usage(uncertain=True))
        cached = 0
    note(
        Usage(
            input_tokens=metadata["input_tokens"],
            output_tokens=metadata["output_tokens"],
            cached_tokens=cached,
        )
    )
