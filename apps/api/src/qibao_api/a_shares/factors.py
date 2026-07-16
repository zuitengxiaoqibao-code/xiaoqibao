from collections.abc import Sequence
from datetime import date
from decimal import Context, Decimal

from qibao_api.a_shares.models import FactorSnapshot
from qibao_api.contracts.bars import DailyBar


class InsufficientHistoryError(ValueError):
    pass


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, start=Decimal("0")) / Decimal(len(values))


def _population_volatility(values: Sequence[Decimal]) -> Decimal:
    average = _mean(values)
    variance = _mean([(value - average) ** 2 for value in values])
    return variance.sqrt(context=Context(prec=28))


def build_factor_snapshot(bars: Sequence[DailyBar], as_of: date) -> FactorSnapshot:
    eligible = sorted(
        (bar for bar in bars if bar.trade_date <= as_of),
        key=lambda bar: bar.trade_date,
    )
    if len(eligible) < 60:
        raise InsufficientHistoryError("at least 60 historical bars are required")
    symbols = {bar.symbol for bar in eligible}
    if len(symbols) != 1:
        raise ValueError("factor history must contain exactly one symbol")
    trade_dates = [bar.trade_date for bar in eligible]
    if len(set(trade_dates)) != len(trade_dates):
        raise ValueError("factor history must contain one bar per trade date")
    sources = {bar.source for bar in eligible}
    if len(sources) != 1:
        raise ValueError("factor history must contain exactly one source")
    window = eligible[-60:]
    latest = window[-1]
    closes = [bar.close for bar in window]
    volumes = [Decimal(bar.volume) for bar in window]
    amounts = [bar.amount for bar in window]
    daily_returns = [
        closes[index] / closes[index - 1] - Decimal("1")
        for index in range(len(closes) - 20, len(closes))
    ]
    peak = max(closes)
    drawdown = latest.close / peak - Decimal("1")
    ma20 = _mean(closes[-20:])
    average_volume_20 = _mean(volumes[-20:])

    return FactorSnapshot(
        symbol=latest.symbol,
        as_of=as_of,
        latest_trade_date=latest.trade_date,
        close=latest.close,
        return_5d=latest.close / closes[-6] - Decimal("1"),
        return_20d=latest.close / closes[-21] - Decimal("1"),
        distance_ma20=latest.close / ma20 - Decimal("1"),
        volume_ratio_5_20=(
            _mean(volumes[-5:]) / average_volume_20
            if average_volume_20 > 0
            else Decimal("0")
        ),
        volatility_20d=_population_volatility(daily_returns),
        drawdown_60d=drawdown,
        liquidity_amount_20d=_mean(amounts[-20:]),
        source=latest.source,
    )
