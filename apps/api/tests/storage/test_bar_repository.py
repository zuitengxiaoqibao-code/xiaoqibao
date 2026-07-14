from datetime import date
from decimal import Decimal

import duckdb

from qibao_api.contracts.bars import DailyBar
from qibao_api.storage.bar_repository import BarRepository


def make_bar(close: str = "9.50") -> DailyBar:
    return DailyBar(
        symbol="600000",
        trade_date=date(2026, 7, 13),
        open=Decimal("9.10"),
        high=Decimal("9.80"),
        low=Decimal("9.00"),
        close=Decimal(close),
        volume=1000,
        amount=Decimal("9500"),
        source="mootdx",
    )


def test_upsert_replaces_same_symbol_and_date(tmp_path) -> None:
    repository = BarRepository(tmp_path / "market.duckdb", tmp_path / "parquet")
    repository.upsert([make_bar()])

    repository.upsert([make_bar("9.60")])

    bars = repository.latest("600000", 10)
    assert len(bars) == 1
    assert bars[0].close == Decimal("9.60")


def test_export_parquet_contains_symbol_rows(tmp_path) -> None:
    repository = BarRepository(tmp_path / "market.duckdb", tmp_path / "parquet")
    repository.upsert([make_bar()])

    path = repository.export_parquet("600000")

    assert path.exists()
    with duckdb.connect() as connection:
        count = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
    assert count == 1


def test_trade_dates_are_distinct_and_descending(tmp_path) -> None:
    repository = BarRepository(tmp_path / "market.duckdb", tmp_path / "parquet")
    repository.upsert([make_bar()])

    assert repository.trade_dates(limit=10) == [date(2026, 7, 13)]
