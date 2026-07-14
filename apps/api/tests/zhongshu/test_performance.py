from datetime import date, timedelta
from decimal import Decimal

from qibao_api.contracts.bars import DailyBar
from qibao_api.contracts.backtest import EquityPoint, Trade
from qibao_api.zhongshu.performance import (
    market_regime_attribution,
    performance_metrics,
    max_drawdown,
    split_bars,
)


def test_max_drawdown_uses_peak_to_trough_loss() -> None:
    assert max_drawdown([Decimal("100"), Decimal("120"), Decimal("90")]) == Decimal("0.2500")


def test_split_bars_is_chronological_and_non_overlapping() -> None:
    bars = [
        DailyBar(symbol="600000", trade_date=date(2026, 1, 1) + timedelta(days=index),
            open=Decimal("10"), high=Decimal("11"), low=Decimal("9"), close=Decimal("10"),
            volume=100, amount=Decimal("1000"), source="fixture")
        for index in range(10)
    ]

    train, validation, out_of_sample = split_bars(bars, Decimal("0.6"), Decimal("0.2"))

    assert len(train) == 6
    assert len(validation) == 2
    assert len(out_of_sample) == 2
    assert train[-1].trade_date < validation[0].trade_date < out_of_sample[0].trade_date


def test_performance_metrics_use_closed_trades_and_equity_returns() -> None:
    start = date(2026, 1, 1)
    points = [
        EquityPoint(trade_date=start + timedelta(days=index), equity=Decimal(value),
                    cash=Decimal(value), shares=0, market_value=0)
        for index, value in enumerate(["100", "110", "99", "108"])
    ]
    trades = [
        Trade(side="buy", signal_date=start, trade_date=start, price=Decimal("10"),
              shares=100, gross_amount=Decimal("1000"), fees=Decimal("1")),
        Trade(side="sell", signal_date=start, trade_date=start + timedelta(days=1),
              price=Decimal("12"), shares=100, gross_amount=Decimal("1200"), fees=Decimal("1")),
        Trade(side="buy", signal_date=start, trade_date=start + timedelta(days=2),
              price=Decimal("11"), shares=100, gross_amount=Decimal("1100"), fees=Decimal("1")),
        Trade(side="sell", signal_date=start, trade_date=start + timedelta(days=3),
              price=Decimal("10"), shares=100, gross_amount=Decimal("1000"), fees=Decimal("1")),
    ]

    metrics = performance_metrics(points, trades)

    assert metrics.closed_trade_count == 2
    assert metrics.win_rate == Decimal("0.5000")
    assert metrics.profit_loss_ratio == Decimal("1.9412")
    assert metrics.turnover_rate == Decimal("41.2470")
    assert metrics.annualized_volatility == Decimal("1.7928")


def test_market_regime_attribution_uses_only_trailing_prices() -> None:
    start = date(2026, 1, 1)
    closes = [Decimal("10") + Decimal(index) for index in range(6)]
    bars = [
        DailyBar(symbol="600000", trade_date=start + timedelta(days=index),
                 open=value, high=value, low=value, close=value,
                 volume=100, amount=Decimal("1000"), source="fixture")
        for index, value in enumerate(closes)
    ]
    points = [
        EquityPoint(trade_date=bar.trade_date, equity=Decimal("100") + Decimal(index * 2),
                    cash=Decimal("100"), shares=0, market_value=Decimal(index * 2))
        for index, bar in enumerate(bars)
    ]

    original = market_regime_attribution(bars, points, lookback=2, threshold=Decimal("0.05"))
    bars[-1] = bars[-1].model_copy(update={"close": Decimal("1")})
    changed = market_regime_attribution(bars, points, lookback=2, threshold=Decimal("0.05"))

    assert original[0].name == "bull"
    assert original[0].bar_count == 3
    assert changed[0].bar_count == 3
    assert changed == original
    assert original[0].total_return == Decimal("0.0577")
