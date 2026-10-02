"""Offline token accounting with bundled OpenAI o200k ranks and Unicode-safe clipping."""

import json
from functools import lru_cache
from pathlib import Path

import tiktoken
from tiktoken.load import load_tiktoken_bpe


@lru_cache(maxsize=1)
def tokenizer() -> tiktoken.Encoding:
    """Load local assets only; first use must never fetch tokenizer data."""
    data = Path(__file__).with_name("data")
    pattern = json.loads((data / "tokenizer.json").read_text())["pattern"]
    return tiktoken.Encoding(
        name="voice_delegate_o200k",
        pat_str=pattern,
        mergeable_ranks=load_tiktoken_bpe(str(data / "o200k_base.tiktoken")),
        special_tokens={},
    )


def count_tokens(text: str) -> int:
    """Count ordinary text, including strings resembling special tokens."""
    return len(tokenizer().encode(text))


def truncate(text: str, budget: int, *, max_bytes: int | None = None) -> str:
    """Keep a valid UTF-8 prefix within both budgets, including a truncation marker."""
    if budget < 1:
        message = "Token budget must be positive"
        raise ValueError(message)
    # Bound processing of unusually large worker output before encoding it.
    source = text[:100_000]
    if (
        len(text) <= 100_000
        and count_tokens(source) <= budget
        and (max_bytes is None or len(source.encode()) <= max_bytes)
    ):
        return source
    suffix = "…"
    tokens = tokenizer().encode(source)
    for length in range(min(len(tokens), budget), -1, -1):
        candidate = (
            tokenizer().decode_bytes(tokens[:length]).decode("utf-8", errors="ignore") + suffix
        )
        if count_tokens(candidate) <= budget and (
            max_bytes is None or len(candidate.encode()) <= max_bytes
        ):
            return candidate
    return ""
