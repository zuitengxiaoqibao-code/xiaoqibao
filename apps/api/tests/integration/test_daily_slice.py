from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from qibao_api.contracts.market import AssetKind, DataQuality, Quote
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.storage.database import create_schema
from qibao_api.storage.quote_repository import QuoteRepository
from qibao_api.xingbu.gate import RiskGate


class StaleSource:
    async def fetch(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol,
            asset=AssetKind.A_SHARE,
            name="浦发银行",
            price=Decimal("10.25"),
            previous_close=Decimal("10.10"),
            observed_at=datetime(2026, 7, 13, 9, 30),
            source="fixture",
            quality=DataQuality.FRESH,
        )


@pytest.mark.asyncio
async def test_pipeline_persists_quote_and_blocks_stale_data(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    create_schema(engine)
    repository = QuoteRepository(engine)
    pipeline = ResearchPipeline(
        StaleSource(),
        repository,
        RiskGate(),
        clock=lambda: datetime(2026, 7, 13, 10, 40),
    )

    result = await pipeline.run("600000")

    stored = repository.latest("600000")
    assert result.action == "blocked"
    assert stored is not None
    assert stored.quality == DataQuality.STALE
