from datetime import date, timedelta
from decimal import Decimal

from qibao_api.contracts.bars import DailyBar
from qibao_api.zhongshu.performance import max_drawdown, split_bars


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
