"""Bound per-client HTTP traffic in one process before buffering request bodies."""

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import ip_address

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass
class Bucket:
    tokens: float
    updated: float


class RateLimitMiddleware:
    """Token buckets with bounded storage; proxy headers require explicit trust."""

    def __init__(
        self,
        app: ASGIApp,
        trust_proxy: bool = False,
        rate: float = 20,
        burst: int = 100,
        max_clients: int = 10000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if rate <= 0 or burst < 1 or max_clients < 1:
            raise ValueError("Rate limiter budgets must be positive")
        self.app = app
        self.trust_proxy = trust_proxy
        self.rate = rate
        self.burst = burst
        self.max_clients = max_clients
        self.clock = clock
        self.buckets: OrderedDict[str, Bucket] = OrderedDict()

    def client(self, scope: Scope) -> str:
        client = scope.get("client")
        address = str(client[0]) if client else "unknown"
        if self.trust_proxy:
            for name, value in scope.get("headers", []):
                if name.lower() == b"x-forwarded-for":
                    try:
                        return str(ip_address(value.decode("ascii").split(",", 1)[0].strip()))
                    except (UnicodeError, ValueError):
                        break
        return address

    def allow(self, address: str) -> bool:
        now = self.clock()
        # An idle, fully replenished bucket can be discarded without resetting a limit.
        while self.buckets:
            oldest = next(iter(self.buckets.values()))
            if now - oldest.updated < self.burst / self.rate:
                break
            self.buckets.popitem(last=False)
        bucket = self.buckets.get(address)
        if bucket is None:
            if len(self.buckets) >= self.max_clients:
                return False
            bucket = Bucket(float(self.burst), now)
            self.buckets[address] = bucket
        bucket.tokens = min(self.burst, bucket.tokens + max(0, now - bucket.updated) * self.rate)
        bucket.updated = now
        self.buckets.move_to_end(address)
        if bucket.tokens < 1:
            return False
        bucket.tokens -= 1
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not self.allow(self.client(scope)):
            await JSONResponse(
                {"detail": "Request rate limit exceeded"},
                status_code=429,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)
