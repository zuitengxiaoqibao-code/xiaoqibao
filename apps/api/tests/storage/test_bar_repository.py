from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import duckdb
import pytest

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


def make_history(symbol: str, count: int, start: date = date(2026, 1, 1)) -> list[DailyBar]:
    bars = []
    for index in range(count):
        close = Decimal("10") + Decimal(index) / Decimal("100")
        bars.append(DailyBar(
            symbol=symbol, trade_date=start + timedelta(days=index), open=close,
            high=close + Decimal("0.1"), low=close - Decimal("0.1"), close=close,
            volume=100_000, amount=close * Decimal("100000"), source="fixture",
        ))
    return bars


def test_repository_returns_only_symbols_with_enough_history(tmp_path) -> None:
    repository = BarRepository(tmp_path / "market.duckdb", tmp_path / "parquet")
    repository.upsert(make_history("600000", 80) + make_history("000001", 40))
    as_of = date(2026, 3, 31)

    assert repository.symbols_with_history(60, as_of) == ["600000"]


def test_latest_many_respects_as_of_and_returns_chronological_bars(tmp_path) -> None:
    repository = BarRepository(tmp_path / "market.duckdb", tmp_path / "parquet")
    bars = make_history("600000", 80)
    repository.upsert(bars)
    as_of = bars[-2].trade_date

    result = repository.latest_many(["600000"], limit=60, as_of=as_of)

    assert list(result) == ["600000"]
    assert len(result["600000"]) == 60
    assert result["600000"][0].trade_date < result["600000"][-1].trade_date
    assert result["600000"][-1].trade_date == as_of


def test_latest_many_rejects_non_a_share_symbols(tmp_path) -> None:
    repository = BarRepository(tmp_path / "market.duckdb", tmp_path / "parquet")

    with pytest.raises(ValueError, match="A-share"):
        repository.latest_many(["113001"], limit=60, as_of=date(2026, 7, 14))


def test_cutoff_excludes_bars_ingested_after_decision_window(tmp_path) -> None:
    repository = BarRepository(tmp_path / "market.duckdb", tmp_path / "parquet")
    repository.upsert(make_history("600000", 60))
    cutoff = datetime(2026, 7, 15, 9, 25, tzinfo=UTC)
    with duckdb.connect(str(repository.database_path)) as connection:
        connection.execute(
            "UPDATE daily_bars SET ingested_at = ?",
            [datetime(2026, 7, 15, 9, 26)],
        )

    assert repository.symbols_with_history(60, date(2026, 7, 15), cutoff=cutoff) == []
    assert repository.latest_many(
        ["600000"], 60, date(2026, 7, 15), cutoff=cutoff,
    ) == {"600000": []}
