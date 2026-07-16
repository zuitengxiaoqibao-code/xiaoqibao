from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine

from qibao_api.contracts.market import AssetKind, DataQuality, Quote
from qibao_api.storage.database import create_schema
from qibao_api.storage.quote_repository import QuoteRepository


def test_quote_round_trip() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
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
    create_schema(engine)
    repository = QuoteRepository(engine)

    repository.save(quote)

    assert repository.latest("600000") == quote


def test_latest_returns_none_when_symbol_has_no_snapshots() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)

    assert QuoteRepository(engine).latest("000001") is None
