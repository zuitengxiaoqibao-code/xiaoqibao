from decimal import Decimal, ROUND_DOWN

from qibao_api.contracts.bars import DailyBar


def max_drawdown(equity_values: list[Decimal]) -> Decimal:
    peak = Decimal("0")
    worst = Decimal("0")
    for equity in equity_values:
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


def split_bars(
    bars: list[DailyBar],
    train_ratio: Decimal,
    validation_ratio: Decimal,
) -> tuple[list[DailyBar], list[DailyBar], list[DailyBar]]:
    if train_ratio <= 0 or validation_ratio <= 0 or train_ratio + validation_ratio >= 1:
        raise ValueError("dataset ratios must be positive and total less than one")
    ordered = sorted(bars, key=lambda bar: bar.trade_date)
    train_end = int(Decimal(len(ordered)) * train_ratio)
    validation_end = train_end + int(Decimal(len(ordered)) * validation_ratio)
    return ordered[:train_end], ordered[train_end:validation_end], ordered[validation_end:]
