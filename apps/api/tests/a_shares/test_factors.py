from datetime import date, timedelta
from decimal import Decimal

import pytest

from qibao_api.a_shares.factors import InsufficientHistoryError, build_factor_snapshot
from qibao_api.contracts.bars import DailyBar


def make_bars(
    count: int,
    *,
    symbol: str = "600000",
    start: date = date(2026, 4, 1),
) -> list[DailyBar]:
    bars = []
    for index in range(count):
        close = Decimal("10") + Decimal(index) / Decimal("10")
        bars.append(DailyBar(
            symbol=symbol,
            trade_date=start + timedelta(days=index),
            open=close,
            high=close + Decimal("0.20"),
            low=close - Decimal("0.20"),
            close=close,
            volume=100_000 + index * 1_000,
            amount=close * Decimal(100_000 + index * 1_000),
            source="fixture",
        ))
    return bars


def test_factor_snapshot_uses_only_bars_on_or_before_as_of() -> None:
    bars = make_bars(80)
    as_of = bars[-1].trade_date
    future = DailyBar(
        symbol="600000",
        trade_date=as_of + timedelta(days=1),
        open=Decimal("999"), high=Decimal("1000"), low=Decimal("998"),
        close=Decimal("999"), volume=9_999_999, amount=Decimal("9990000000"),
        source="future-fixture",
    )

    result = build_factor_snapshot([*bars, future], as_of=as_of)

    assert result.as_of == as_of
    assert result.close == bars[-1].close
    assert result.source == "fixture"
    assert result.factor_version == "a-share-factors-v1"


def test_factor_snapshot_rejects_less_than_sixty_bars() -> None:
    bars = make_bars(59)

    with pytest.raises(InsufficientHistoryError, match="60"):
        build_factor_snapshot(bars, as_of=bars[-1].trade_date)


def test_factor_snapshot_calculates_auditable_metrics() -> None:
    bars = make_bars(80)

    result = build_factor_snapshot(bars, as_of=bars[-1].trade_date)

    assert result.return_5d == (bars[-1].close / bars[-6].close - 1)
    assert result.return_20d == (bars[-1].close / bars[-21].close - 1)
    assert result.liquidity_amount_20d == sum(
        (bar.amount for bar in bars[-20:]), start=Decimal("0")
    ) / Decimal("20")
    assert result.volume_ratio_5_20 > 1
    assert result.drawdown_60d == 0


def test_factor_snapshot_keeps_requested_as_of_on_non_trading_day() -> None:
    bars = make_bars(80)
    requested_as_of = bars[-1].trade_date + timedelta(days=2)

    result = build_factor_snapshot(bars, as_of=requested_as_of)

    assert result.as_of == requested_as_of
