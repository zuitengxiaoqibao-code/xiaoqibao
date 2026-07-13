from datetime import date, timedelta
from decimal import Decimal

from qibao_api.contracts.backtest import BacktestRequest
from qibao_api.contracts.bars import DailyBar
from qibao_api.zhongshu.backtest import BacktestEngine


def bars_from_prices(closes: list[str], opens: list[str] | None = None) -> list[DailyBar]:
    opens = opens or closes
    start = date(2026, 7, 1)
    bars = []
    for index, (open_value, close_value) in enumerate(zip(opens, closes, strict=True)):
        open_price = Decimal(open_value)
        close_price = Decimal(close_value)
        bars.append(DailyBar(
            symbol="600000", trade_date=start + timedelta(days=index), open=open_price,
            high=max(open_price, close_price) + Decimal("0.10"),
            low=min(open_price, close_price) - Decimal("0.10"), close=close_price,
            volume=100000, amount=Decimal("1000000"), source="fixture",
        ))
    return bars


def test_cross_signal_executes_at_next_day_open() -> None:
    bars = bars_from_prices(["10", "9", "8", "12", "13"])
    request = BacktestRequest(fast_window=2, slow_window=3, commission_rate=0, slippage_rate=0)

    result = BacktestEngine().run(request, bars)

    assert len(result.trades) == 1
    assert result.trades[0].signal_date == bars[3].trade_date
    assert result.trades[0].trade_date == bars[4].trade_date
    assert result.trades[0].price == bars[4].open


def test_costs_reduce_ending_equity() -> None:
    bars = bars_from_prices(
        ["10", "9", "8", "12", "14"],
        ["10", "9", "8", "12", "12.50"],
    )
    free = BacktestEngine().run(BacktestRequest(fast_window=2, slow_window=3, commission_rate=0, slippage_rate=0), bars)
    costly = BacktestEngine().run(BacktestRequest(fast_window=2, slow_window=3), bars)

    assert costly.ending_equity < free.ending_equity
    assert costly.total_cost > 0


def test_limit_up_open_rejects_buy() -> None:
    bars = bars_from_prices(
        ["10", "9", "8", "12", "13.20"],
        ["10", "9", "8", "12", "13.20"],
    )

    result = BacktestEngine().run(BacktestRequest(fast_window=2, slow_window=3), bars)

    assert result.trades == []
    assert any("涨停" in warning for warning in result.warnings)
