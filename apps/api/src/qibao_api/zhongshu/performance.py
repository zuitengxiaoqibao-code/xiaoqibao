from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from qibao_api.contracts.backtest import (
    EquityPoint,
    MarketRegimeResult,
    PerformanceMetrics,
    Trade,
)
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


def performance_metrics(
    equity_curve: list[EquityPoint], trades: list[Trade]
) -> PerformanceMetrics:
    returns = [
        current.equity / previous.equity - Decimal("1")
        for previous, current in zip(equity_curve, equity_curve[1:], strict=False)
        if previous.equity > 0
    ]
    volatility = Decimal("0")
    if len(returns) >= 2:
        mean = sum(returns, Decimal("0")) / Decimal(len(returns))
        variance = sum(
            ((value - mean) ** 2 for value in returns), Decimal("0")
        ) / Decimal(len(returns) - 1)
        volatility = variance.sqrt() * Decimal("252").sqrt()

    closed_results: list[Decimal] = []
    open_cost: Decimal | None = None
    for trade in trades:
        if trade.side == "buy":
            open_cost = trade.gross_amount + trade.fees
        elif open_cost is not None:
            closed_results.append(trade.gross_amount - trade.fees - open_cost)
            open_cost = None
    wins = [value for value in closed_results if value > 0]
    losses = [-value for value in closed_results if value < 0]
    win_rate = _ratio(len(wins), len(closed_results))
    profit_loss_ratio = None
    if wins and losses:
        average_win = sum(wins, Decimal("0")) / Decimal(len(wins))
        average_loss = sum(losses, Decimal("0")) / Decimal(len(losses))
        profit_loss_ratio = _quantize(average_win / average_loss)

    average_equity = Decimal("0")
    if equity_curve:
        average_equity = sum(
            (point.equity for point in equity_curve), Decimal("0")
        ) / Decimal(len(equity_curve))
    gross_turnover = sum((trade.gross_amount for trade in trades), Decimal("0"))
    turnover_rate = gross_turnover / average_equity if average_equity > 0 else Decimal("0")
    return PerformanceMetrics(
        annualized_volatility=_quantize(volatility),
        win_rate=win_rate,
        profit_loss_ratio=profit_loss_ratio,
        turnover_rate=_quantize(turnover_rate),
        closed_trade_count=len(closed_results),
    )


def market_regime_attribution(
    bars: list[DailyBar],
    equity_curve: list[EquityPoint],
    *,
    lookback: int = 20,
    threshold: Decimal = Decimal("0.05"),
) -> list[MarketRegimeResult]:
    if lookback < 1 or threshold <= 0:
        raise ValueError("regime lookback and threshold must be positive")
    ordered_bars = sorted(bars, key=lambda item: item.trade_date)
    equity_by_date = {point.trade_date: point.equity for point in equity_curve}
    grouped: dict[str, list[Decimal]] = {"bull": [], "bear": [], "sideways": []}
    for index in range(lookback + 1, len(ordered_bars)):
        current = ordered_bars[index]
        previous = ordered_bars[index - 1]
        if previous.trade_date not in equity_by_date or current.trade_date not in equity_by_date:
            continue
        trailing_return = (
            previous.close / ordered_bars[index - lookback - 1].close - Decimal("1")
        )
        regime = (
            "bull" if trailing_return > threshold
            else "bear" if trailing_return < -threshold
            else "sideways"
        )
        prior_equity = equity_by_date[previous.trade_date]
        if prior_equity > 0:
            grouped[regime].append(equity_by_date[current.trade_date] / prior_equity - Decimal("1"))
    results = []
    for name in ("bull", "bear", "sideways"):
        compounded = Decimal("1")
        for value in grouped[name]:
            compounded *= Decimal("1") + value
        results.append(MarketRegimeResult(
            name=name,
            bar_count=len(grouped[name]),
            total_return=_quantize(compounded - Decimal("1")),
        ))
    return results


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0.0000")
    return _quantize(Decimal(numerator) / Decimal(denominator))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
