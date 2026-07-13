from datetime import datetime
from decimal import Decimal

import pytest

from qibao_api.contracts.market import AssetKind, DataQuality, Quote
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.xingbu.gate import RiskGate


class StaticQuoteSource:
    def __init__(self, quote: Quote) -> None:
        self.quote = quote

    async def fetch(self, symbol: str) -> Quote:
        assert symbol == self.quote.symbol
        return self.quote


class RecordingRepository:
    def __init__(self) -> None:
        self.saved: list[Quote] = []

    def save(self, quote: Quote) -> None:
        self.saved.append(quote)


@pytest.mark.asyncio
async def test_pipeline_rechecks_freshness_before_research() -> None:
    quote = Quote(
        symbol="600000",
        asset=AssetKind.A_SHARE,
        name="浦发银行",
        price=Decimal("10.25"),
        previous_close=Decimal("10.10"),
        observed_at=datetime(2026, 7, 13, 10, 30),
        source="tencent",
        quality=DataQuality.FRESH,
    )
    repository = RecordingRepository()
    pipeline = ResearchPipeline(
        StaticQuoteSource(quote),
        repository,
        RiskGate(),
        clock=lambda: datetime(2026, 7, 13, 10, 40),
    )

    result = await pipeline.run("600000")

    assert result.action == "blocked"
    assert repository.saved[0].quality == DataQuality.STALE
