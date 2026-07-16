from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from qibao_api.a_shares.instrument_directory import (
    AShareInstrument,
    AShareInstrumentDirectory,
)


NOW = datetime(2026, 7, 15, 1, 30, tzinfo=timezone.utc)


def instrument(
    symbol: str = "600000",
    name: str = "浦发银行",
    observed_at: datetime = NOW,
) -> AShareInstrument:
    exchange = "sh" if symbol.startswith("6") else "sz"
    return AShareInstrument(
        symbol=symbol,
        name=name,
        exchange=exchange,
        observed_at=observed_at,
        quote_quality="ready",
    )


def test_search_prioritizes_exact_code_then_name_prefix(tmp_path: Path) -> None:
    directory = AShareInstrumentDirectory(tmp_path / "instruments.sqlite3")
    directory.observe(instrument(symbol="600000", name="浦发银行"))
    directory.observe(instrument(symbol="000001", name="平安银行"))

    assert [item.symbol for item in directory.search("600000", 10)] == ["600000"]
    assert [item.symbol for item in directory.search("平安", 10)] == ["000001"]
    assert [item.symbol for item in directory.search("银行", 10)] == ["000001", "600000"]


@pytest.mark.parametrize("symbol", ["113065", "399001", "000300"])
def test_directory_rejects_convertible_bond_and_index_codes(
    tmp_path: Path, symbol: str
) -> None:
    directory = AShareInstrumentDirectory(tmp_path / "instruments.sqlite3")

    with pytest.raises(ValueError, match="A-share"):
        directory.observe(instrument(symbol=symbol))


def test_resolve_returns_latest_observation_without_deleting_history(tmp_path: Path) -> None:
    database_path = tmp_path / "instruments.sqlite3"
    directory = AShareInstrumentDirectory(database_path)
    directory.observe(instrument(name="旧名称"))
    directory.observe(instrument(name="新名称", observed_at=NOW + timedelta(minutes=1)))
    directory.close()

    reopened = AShareInstrumentDirectory(database_path)
    assert reopened.resolve("600000") == instrument(
        name="新名称", observed_at=NOW + timedelta(minutes=1)
    )
    reopened.close()
    with sqlite3.connect(database_path) as connection:
        count = connection.execute(
            "SELECT count(*) FROM a_share_instrument_observations WHERE symbol = '600000'"
        ).fetchone()[0]
    assert count == 2


def test_resolve_at_never_returns_identity_observed_after_cutoff(tmp_path: Path) -> None:
    directory = AShareInstrumentDirectory(tmp_path / "instruments.sqlite3")
    directory.observe(instrument(name="历史名称", observed_at=NOW))
    directory.observe(instrument(name="未来名称", observed_at=NOW + timedelta(days=1)))
    assert directory.resolve_at("600000", NOW + timedelta(hours=1)).name == "历史名称"
    assert directory.resolve_at("600000", NOW - timedelta(seconds=1)) is None


def test_mixed_offset_observations_resolve_by_instant(tmp_path: Path) -> None:
    directory = AShareInstrumentDirectory(tmp_path / "instruments.sqlite3")
    directory.observe(
        instrument(
            name="较晚观察",
            observed_at=datetime.fromisoformat("2026-07-15T02:00:00+00:00"),
        )
    )
    directory.observe(
        instrument(
            name="较早观察",
            observed_at=datetime.fromisoformat("2026-07-15T10:30:00+09:00"),
        )
    )

    assert directory.resolve("600000").name == "较晚观察"
    assert directory.resolve("600000").observed_at == datetime.fromisoformat(
        "2026-07-15T02:00:00+00:00"
    )


def test_two_directory_instances_can_observe_and_search_safely(tmp_path: Path) -> None:
    database_path = tmp_path / "instruments.sqlite3"
    first = AShareInstrumentDirectory(database_path)
    second = AShareInstrumentDirectory(database_path)

    def write(directory, start: int) -> None:
        for offset in range(start, start + 10):
            directory.observe(
                instrument(
                    name=f"银行{offset}",
                    observed_at=NOW + timedelta(seconds=offset),
                )
            )
            directory.search("银行", 10)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, first, 0), executor.submit(write, second, 10)]
        for future in futures:
            future.result()

    assert first.resolve("600000").name == "银行19"
    assert second.resolve("600000").name == "银行19"
    first.close()
    second.close()


def test_search_empty_query_and_invalid_limit_are_rejected(tmp_path: Path) -> None:
    directory = AShareInstrumentDirectory(tmp_path / "instruments.sqlite3")

    with pytest.raises(ValueError, match="query"):
        directory.search("  ", 10)
    with pytest.raises(ValueError, match="limit"):
        directory.search("银行", 0)
