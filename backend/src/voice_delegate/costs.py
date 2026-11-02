"""Session-local estimates from numeric counters and a frozen, versioned price snapshot."""

import json
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from voice_delegate_agent.usage import Usage

from voice_delegate.observability.metrics import Metrics


class Rate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    usd: float | None = Field(default=None, ge=0, le=1000000)
    source: str


class Prices(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = Field(min_length=1, max_length=80)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    rates: dict[str, Rate] = Field(max_length=64)

    @classmethod
    def load(cls, path: str = "") -> "Prices":
        raw = (
            Path(path).read_bytes()
            if path
            else files("voice_delegate").joinpath("prices/2026-11-02.json").read_bytes()
        )
        if len(raw) > 65536:
            message = "Price file exceeds limit"
            raise ValueError(message)
        return cls.model_validate(json.loads(raw))


class CostSummary(BaseModel):
    version: str
    price_date: str
    estimated_usd: float
    components: dict[str, float]
    usage: Usage
    voice_seconds: float
    partial: bool
    unpriced: list[str]
    final: bool


class CostLedger:
    def __init__(
        self,
        prices: Prices,
        adapter: str,
        worker_model: str,
        clock: Callable[[], float],
        metrics: Metrics,
    ) -> None:
        self.prices = prices.model_copy(deep=True)
        self.adapter = adapter
        self.worker_model = worker_model
        self.clock = clock
        self.metrics = metrics
        self.usage = Usage()
        self.seconds: dict[str, float] = {}
        self.started: float | None = None
        self.final = False
        self.emitted: dict[str, float] = {}

    def record(self, usage: Usage) -> None:
        self.usage = self.usage.plus(usage)
        self.snapshot()

    def connect(self, adapter: str | None = None) -> None:
        if self.final:
            return
        self._tick()
        if adapter is not None:
            self.adapter = adapter
        self.started = self.clock()

    def _tick(self) -> None:
        if self.started is not None:
            now = self.clock()
            self.seconds[self.adapter] = self.seconds.get(self.adapter, 0) + max(
                0, now - self.started
            )
            self.started = now

    def close(self, confirmed: bool) -> None:
        if not self.final:
            self._tick()
            self.started = None
            self.final = True
            if not confirmed:
                self.usage = self.usage.plus(Usage(uncertain=True))
        self.snapshot()

    def snapshot(self) -> CostSummary:
        self._tick()
        components: dict[str, float] = {"voice": 0, "worker": 0, "decisions": 0, "web_search": 0}
        unpriced: list[str] = []

        def price(component: str, key: str, amount: float) -> None:
            if not amount:
                return
            rate = self.prices.rates.get(key)
            if rate is None or rate.usd is None:
                unpriced.append(key)
            else:
                components[component] += amount * rate.usd

        for adapter, seconds in self.seconds.items():
            price("voice", "voice." + adapter + ".second", seconds)
        usage = self.usage
        prefix = "worker." + self.worker_model
        price("worker", prefix + ".input_token", max(0, usage.input_tokens - usage.cached_tokens))
        price("worker", prefix + ".cached_token", usage.cached_tokens)
        price("worker", prefix + ".output_token", usage.output_tokens)
        price("decisions", "decisions.input_token", usage.decision_tokens)
        price("web_search", "tavily.basic_search", usage.web_calls)
        for component, amount in components.items():
            delta = max(0, amount - self.emitted.get(component, 0))
            if delta:
                self.metrics.session_cost.add(delta, {"component": component})
                self.emitted[component] = amount
        return CostSummary(
            version=self.prices.version,
            price_date=self.prices.date,
            estimated_usd=sum(components.values()),
            components=components,
            usage=usage,
            voice_seconds=sum(self.seconds.values()),
            partial=usage.uncertain or bool(unpriced),
            unpriced=sorted(set(unpriced)),
            final=self.final,
        )
