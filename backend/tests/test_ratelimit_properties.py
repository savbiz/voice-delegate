"""The token bucket's guarantees hold for any traffic pattern, not just the examples."""

from hypothesis import given, settings
from hypothesis import strategies as st
from starlette.responses import Response
from starlette.types import Receive, Scope, Send
from voice_delegate.limits.ratelimit import RateLimitMiddleware

RATE = 2.0
BURST = 5
# Mostly short gaps, so demand exceeds the refill rate and the bucket actually runs dry.
GAP = st.one_of(
    st.just(0.0),
    st.floats(min_value=0, max_value=0.6, allow_nan=False),
    st.floats(min_value=0, max_value=4, allow_nan=False),
)
GAPS = st.lists(GAP, max_size=80)
PROFILE = settings(max_examples=200, deadline=None, derandomize=True, database=None)


async def ok(scope: Scope, receive: Receive, send: Send) -> None:
    await Response("ok")(scope, receive, send)


def limiter(clock: list[float]) -> RateLimitMiddleware:
    return RateLimitMiddleware(ok, rate=RATE, burst=BURST, clock=lambda: clock[0])


@PROFILE
@given(GAPS)
def test_a_client_never_exceeds_burst_plus_refill(gaps: list[float]) -> None:
    now = [0.0]
    bucket = limiter(now)
    allowed = 0
    for gap in gaps:
        now[0] += gap
        allowed += bucket.allow("192.0.2.1")
        assert allowed <= BURST + RATE * now[0] + 1e-6


@PROFILE
@given(GAPS, st.floats(min_value=BURST / RATE, max_value=1000))
def test_an_idle_client_always_regains_its_full_burst(gaps: list[float], idle: float) -> None:
    now = [0.0]
    bucket = limiter(now)
    for gap in gaps:
        now[0] += gap
        bucket.allow("192.0.2.1")
    now[0] += idle
    assert [bucket.allow("192.0.2.1") for _ in range(BURST + 3)] == [True] * BURST + [False] * 3


@PROFILE
@given(st.lists(st.tuples(GAP, st.booleans()), max_size=80))
def test_one_client_cannot_change_anothers_budget(steps: list[tuple[float, bool]]) -> None:
    shared, alone = [0.0], [0.0]
    both, solo = limiter(shared), limiter(alone)
    for gap, noisy in steps:
        shared[0] += gap
        alone[0] += gap
        if noisy:
            both.allow("192.0.2.9")
            both.allow("192.0.2.9")
        assert both.allow("192.0.2.1") == solo.allow("192.0.2.1")
