"""Exact boundaries and error shapes of the limit helpers, pinned by assertion.

A limit that is off by one token, byte or request is a bug that ordinary examples miss, so each
test sits on a boundary: exactly at the limit, one past it, and the empty case.
"""

import json
from typing import Any

import httpx
import pytest
from starlette.responses import Response
from starlette.types import Message, Receive, Scope, Send
from voice_delegate.limits.http import BodyLimitMiddleware
from voice_delegate.limits.ratelimit import RateLimitMiddleware
from voice_delegate.limits.results import clip_worker_result
from voice_delegate.limits.tokens import count_tokens, truncate
from voice_delegate_agent.reference import Source, WorkerResult

WORDS = " a" * 50  # every " a" is one token, and so is the "…" marker


# --- tokens ---------------------------------------------------------------------------------


def test_the_token_budget_must_be_positive() -> None:
    with pytest.raises(ValueError, match=r"^Token budget must be positive$"):
        truncate("text", 0)


def test_text_that_exactly_fits_the_budget_is_returned_unchanged() -> None:
    assert count_tokens(WORDS) == 50
    assert truncate(WORDS, 50) == WORDS
    assert truncate("", 1) == ""


def test_one_token_over_the_budget_is_cut_to_the_longest_prefix_with_a_marker() -> None:
    result = truncate(WORDS, 49)
    # 48 tokens of text plus the one-token marker is the longest result that fits in 49.
    assert result == " a" * 48 + "…"
    assert count_tokens(result) == 49


def test_a_one_token_budget_keeps_only_the_marker() -> None:
    assert truncate(WORDS, 1) == "…"


def test_the_byte_budget_applies_as_well_as_the_token_budget() -> None:
    text = "é" * 40  # two bytes per character
    size = len(text.encode())
    assert truncate(text, 1000, max_bytes=size) == text
    clipped = truncate(text, 1000, max_bytes=size - 1)
    # 38 characters (76 bytes) and the three-byte marker are exactly 79 bytes: the longest fit.
    assert clipped == "é" * 38 + "…"
    assert len(clipped.encode()) == size - 1


def test_a_cut_inside_a_multibyte_character_never_raises_or_leaves_garbage() -> None:
    # Each of these characters is three tokens, so a token cut often falls inside a character.
    text = "🧑" * 200
    for budget in range(1, 9):
        clipped = truncate(text, budget)
        assert "�" not in clipped
        assert clipped.endswith("…")
        assert count_tokens(clipped) <= budget


def test_input_beyond_one_hundred_thousand_characters_is_cut_there() -> None:
    at_limit = "a" * 100_000
    budget = count_tokens(at_limit) + 10
    assert truncate(at_limit, budget) == at_limit
    over = at_limit + "b"
    assert truncate(over, budget) == at_limit + "…"


# --- worker results ---------------------------------------------------------------------------

WEB = Source("w1", "Web", "https://example.com", "Web search", "excerpt", "d")
DOC = Source("d1", "Doc", "docs/x.md", "Architecture", "excerpt", "d")


def test_a_plain_result_is_returned_with_its_own_text_and_no_prefix() -> None:
    result = clip_worker_result(WorkerResult("The answer is 4."), 100)
    assert result.text == "The answer is 4."
    assert result.status == "completed"


def test_cited_web_evidence_survives_when_a_citation_is_retained() -> None:
    result = WorkerResult("It is 4 [1].", sources=(WEB,))
    assert clip_worker_result(result, 100) == result


def test_web_evidence_without_a_surviving_citation_fails_the_task() -> None:
    clipped = clip_worker_result(WorkerResult("It is 4.", sources=(WEB,)), 100)
    assert clipped == WorkerResult(
        "Web result lost its citations; task incomplete.", status="failed"
    )


def test_the_failure_notice_obeys_the_byte_budget_too() -> None:
    clipped = clip_worker_result(WorkerResult("It is 4.", sources=(WEB,)), 100, max_bytes=12)
    assert clipped.status == "failed"
    assert len(clipped.text.encode()) <= 12


def test_documentation_sources_do_not_need_citations() -> None:
    result = WorkerResult("It is 4.", sources=(DOC,))
    assert clip_worker_result(result, 100) == result


def test_a_citation_inside_the_reminder_prefix_is_not_answer_evidence() -> None:
    result = WorkerResult("It is 4.", sources=(WEB,))
    clipped = clip_worker_result(result, 100, prefix="Reminder [1]. ")
    assert clipped.status == "failed"


def test_a_prefix_cut_away_by_the_budget_leaves_no_answer_to_cite() -> None:
    result = WorkerResult("[1] cited", sources=(WEB,))
    clipped = clip_worker_result(result, 2, prefix="A long reminder that cannot fit. ")
    assert clipped.status == "failed"


# --- request body limit -----------------------------------------------------------------------


async def run_body_limit(
    incoming: list[Message], limit: int
) -> tuple[list[Message], list[Message]]:
    sent: list[Message] = []
    seen: list[Message] = []

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(await receive())
        await send({"type": "http.response.start", "status": 200, "headers": []})

    await BodyLimitMiddleware(app, limit)({"type": "http"}, receive, send)
    return sent, seen


async def test_an_oversized_body_gets_a_json_413_that_must_not_be_cached() -> None:
    sent, seen = await run_body_limit([{"type": "http.request", "body": b"x" * 6}], 5)
    assert seen == []
    start, body = sent
    assert start["status"] == 413
    headers = {name.lower(): value for name, value in start["headers"]}
    assert headers[b"cache-control"] == b"no-store"
    assert json.loads(body["body"]) == {"detail": "Request too large"}


async def test_a_message_without_body_or_more_body_is_an_empty_final_chunk() -> None:
    sent, seen = await run_body_limit([{"type": "http.request"}], 5)
    assert sent[0]["status"] == 200
    assert seen == [{"type": "http.request", "body": b"", "more_body": False}]


async def test_a_body_of_exactly_the_limit_is_accepted() -> None:
    sent, seen = await run_body_limit([{"type": "http.request", "body": b"x" * 5}], 5)
    assert sent[0]["status"] == 200
    assert seen[0]["body"] == b"x" * 5


# --- rate limiter ------------------------------------------------------------------------------


async def ok(scope: Scope, receive: Receive, send: Send) -> None:
    await Response("ok")(scope, receive, send)


def make(**options: Any) -> RateLimitMiddleware:
    return RateLimitMiddleware(ok, **options)


def test_defaults_are_twenty_per_second_with_a_burst_of_one_hundred_and_no_proxy_trust() -> None:
    limiter = make()
    assert (limiter.rate, limiter.burst, limiter.max_clients, limiter.trust_proxy) == (
        20,
        100,
        10000,
        False,
    )


@pytest.mark.parametrize(
    "option", [{"rate": 0}, {"burst": 0}, {"max_clients": 0}, {"trusted_proxy_hops": 0}]
)
def test_a_zero_budget_is_rejected(option: dict[str, float]) -> None:
    with pytest.raises(ValueError, match=r"^Rate limiter budgets must be positive$"):
        make(**option)


def test_the_smallest_positive_budgets_are_accepted() -> None:
    limiter = make(rate=0.001, burst=1, max_clients=1, trusted_proxy_hops=1)
    assert limiter.allow("192.0.2.1")
    assert not limiter.allow("192.0.2.1")


def scope(address: tuple[str, int] | None = ("192.0.2.5", 1), *headers: bytes) -> Scope:
    pairs = [(b"x-forwarded-for", value) for value in headers]
    result: Scope = {"type": "http", "headers": pairs}
    if address is not None:
        result["client"] = address
    return result


def test_a_request_without_a_peer_address_shares_one_unknown_bucket() -> None:
    assert make().client(scope(None)) == "unknown"


def test_ipv6_clients_are_grouped_by_their_64_bit_prefix() -> None:
    assert make().client(scope(("2001:db8:1:2:aaaa:bbbb:cccc:dddd", 1))) == "2001:db8:1:2::/64"


def test_forwarded_addresses_are_only_trusted_when_configured() -> None:
    header = b"203.0.113.9, 198.51.100.7"
    assert make().client(scope(("192.0.2.5", 1), header)) == "192.0.2.5"
    assert make(trust_proxy=True).client(scope(("192.0.2.5", 1), header)) == "198.51.100.7"
    assert (
        make(trust_proxy=True, trusted_proxy_hops=2).client(scope(("192.0.2.5", 1), header))
        == "203.0.113.9"
    )


def test_repeated_forwarded_headers_are_joined_before_counting_hops() -> None:
    limiter = make(trust_proxy=True, trusted_proxy_hops=2)
    assert limiter.client(scope(("192.0.2.5", 1), b"1.1.1.1", b"2.2.2.2")) == "1.1.1.1"


def test_idle_clients_are_forgotten_once_their_bucket_would_be_full_again() -> None:
    now = [0.0]
    limiter = RateLimitMiddleware(ok, rate=2, burst=4, clock=lambda: now[0])
    for address in ("192.0.2.1", "192.0.2.2", "192.0.2.3"):
        limiter.allow(address)
    now[0] = 1.0  # a full refill takes burst / rate = 2 seconds
    limiter.allow("192.0.2.4")
    assert len(limiter.buckets) == 4
    now[0] = 3.5
    limiter.allow("192.0.2.4")
    assert list(limiter.buckets) == ["192.0.2.4"]


def test_the_oldest_client_is_dropped_when_the_table_is_full() -> None:
    limiter = RateLimitMiddleware(ok, max_clients=2, clock=lambda: 0.0)
    for address in ("192.0.2.1", "192.0.2.2", "192.0.2.3"):
        limiter.allow(address)
    assert list(limiter.buckets) == ["192.0.2.2", "192.0.2.3"]


def test_a_trusting_limiter_copes_with_a_scope_that_has_no_headers() -> None:
    assert make(trust_proxy=True).client({"type": "http", "client": ("192.0.2.5", 1)}) == (
        "192.0.2.5"
    )


async def test_a_limited_request_is_answered_with_a_json_429() -> None:
    limiter = make(burst=1, rate=0.001)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limiter, client=("192.0.2.1", 1)),
        base_url="http://testserver",
    ) as client:
        assert (await client.get("/")).status_code == 200
        blocked = await client.get("/")
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Request rate limit exceeded"}
    assert blocked.headers["cache-control"] == "no-store"
