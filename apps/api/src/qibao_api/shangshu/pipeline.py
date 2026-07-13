from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from qibao_api.contracts.market import Quote
from qibao_api.contracts.research import ResearchCard
from qibao_api.gongbu.quality import assess_observed_at
from qibao_api.xingbu.gate import RiskGate
from qibao_api.zhongshu.daily_research import build_market_snapshot


class QuoteSource(Protocol):
    async def fetch(self, symbol: str) -> Quote: ...


class QuoteStore(Protocol):
    def save(self, quote: Quote) -> None: ...


class ResearchPipeline:
    def __init__(
        self,
        quote_source: QuoteSource,
        repository: QuoteStore,
        risk_gate: RiskGate,
        clock: Callable[[], datetime] = datetime.now,
        max_age: timedelta = timedelta(minutes=3),
    ) -> None:
        self.quote_source = quote_source
        self.repository = repository
        self.risk_gate = risk_gate
        self.clock = clock
        self.max_age = max_age

    async def run(self, symbol: str) -> ResearchCard:
        quote = await self.quote_source.fetch(symbol)
        quality = assess_observed_at(quote.observed_at, self.clock(), self.max_age)
        assessed_quote = quote.model_copy(update={"quality": quality})
        self.repository.save(assessed_quote)
        return self.risk_gate.review(build_market_snapshot(assessed_quote))

