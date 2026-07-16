from decimal import Decimal

from qibao_api.contracts.backtest import (
    BacktestRequest,
    BacktestResult,
    BacktestSegmentResult,
    EquityPoint,
    Trade,
)
from qibao_api.contracts.bars import DailyBar
from qibao_api.zhongshu.performance import (
    market_regime_attribution,
    max_drawdown,
    performance_metrics,
    split_bars,
)

LIMIT_THRESHOLD = Decimal("0.098")


class BacktestEngine:
    def run(self, request: BacktestRequest, bars: list[DailyBar]) -> BacktestResult:
        ordered = sorted(bars, key=lambda bar: bar.trade_date)
        if len(ordered) <= request.slow_window:
            raise ValueError("not enough bars for selected slow window")

        result = self._run_core(request, ordered)
        train, validation, out_of_sample = split_bars(
            ordered, Decimal("0.6"), Decimal("0.2")
        )
        named_segments = (
            ("train", train),
            ("validation", validation),
            ("out_of_sample", out_of_sample),
        )
        if all(len(segment_bars) > request.slow_window for _, segment_bars in named_segments):
            result.segments = [
                self._attribute_segment(name, segment_bars, result.equity_curve)
                for name, segment_bars in named_segments
            ]
        return result

    def _run_core(
        self, request: BacktestRequest, ordered: list[DailyBar]
    ) -> BacktestResult:

        cash = request.initial_cash
        shares = 0
        trades: list[Trade] = []
        points: list[EquityPoint] = []
        warnings: list[str] = []
        total_cost = Decimal("0")
        pending: tuple[str, object] | None = None

        for index, bar in enumerate(ordered):
            if pending and index > 0:
                side, signal_date = pending
                previous_close = ordered[index - 1].close
                opening_change = bar.open / previous_close - Decimal("1")
                if side == "buy" and shares == 0:
                    if opening_change >= LIMIT_THRESHOLD:
                        warnings.append(f"{bar.trade_date} 接近涨停，买入未成交")
                    else:
                        price = bar.open * (Decimal("1") + request.slippage_rate)
                        affordable = int(cash / (price * (Decimal("1") + request.commission_rate)))
                        quantity = affordable // 100 * 100
                        if quantity >= 100:
                            gross = price * quantity
                            fees = gross * request.commission_rate
                            cash -= gross + fees
                            shares = quantity
                            total_cost += fees + (price - bar.open) * quantity
                            trades.append(Trade(side="buy", signal_date=signal_date,
                                trade_date=bar.trade_date, price=price, shares=quantity,
                                gross_amount=gross, fees=fees))
                elif side == "sell" and shares > 0:
                    if opening_change <= -LIMIT_THRESHOLD:
                        warnings.append(f"{bar.trade_date} 接近跌停，卖出未成交")
                    else:
                        price = bar.open * (Decimal("1") - request.slippage_rate)
                        gross = price * shares
                        fees = gross * request.commission_rate
                        total_cost += fees + (bar.open - price) * shares
                        cash += gross - fees
                        trades.append(Trade(side="sell", signal_date=signal_date,
                            trade_date=bar.trade_date, price=price, shares=shares,
                            gross_amount=gross, fees=fees))
                        shares = 0
                pending = None

            market_value = bar.close * shares
            points.append(EquityPoint(trade_date=bar.trade_date, equity=cash + market_value,
                cash=cash, shares=shares, market_value=market_value))

            if index >= request.slow_window - 1:
                current_fast = self._average(ordered, index, request.fast_window)
                current_slow = self._average(ordered, index, request.slow_window)
                if index >= request.slow_window:
                    previous_fast = self._average(ordered, index - 1, request.fast_window)
                    previous_slow = self._average(ordered, index - 1, request.slow_window)
                    if previous_fast <= previous_slow and current_fast > current_slow:
                        pending = ("buy", bar.trade_date)
                    elif previous_fast >= previous_slow and current_fast < current_slow:
                        pending = ("sell", bar.trade_date)

        ending_equity = points[-1].equity
        total_return = ending_equity / request.initial_cash - Decimal("1")
        return BacktestResult(
            symbol=ordered[0].symbol,
            strategy=request.strategy,
            initial_cash=request.initial_cash,
            ending_equity=ending_equity.quantize(Decimal("0.01")),
            total_return=total_return.quantize(Decimal("0.0001")),
            max_drawdown=max_drawdown([point.equity for point in points]),
            total_cost=total_cost.quantize(Decimal("0.01")),
            metrics=performance_metrics(points, trades),
            market_regimes=market_regime_attribution(ordered, points),
            trades=trades,
            equity_curve=points,
            warnings=warnings,
        )

    def _attribute_segment(
        self, name: str, bars: list[DailyBar], equity_curve: list[EquityPoint]
    ) -> BacktestSegmentResult:
        start_date = bars[0].trade_date
        end_date = bars[-1].trade_date
        start_index = next(
            index for index, point in enumerate(equity_curve)
            if point.trade_date == start_date
        )
        end_index = next(
            index for index, point in enumerate(equity_curve)
            if point.trade_date == end_date
        )
        anchor_index = max(0, start_index - 1)
        attribution_points = equity_curve[anchor_index:end_index + 1]
        starting_equity = attribution_points[0].equity
        ending_equity = attribution_points[-1].equity
        return BacktestSegmentResult(
            name=name,
            start_date=start_date,
            end_date=end_date,
            bar_count=len(bars),
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            total_return=(ending_equity / starting_equity - Decimal("1")).quantize(
                Decimal("0.0001")
            ),
            max_drawdown=max_drawdown([point.equity for point in attribution_points]),
        )

    @staticmethod
    def _average(bars: list[DailyBar], index: int, window: int) -> Decimal:
        closes = [bar.close for bar in bars[index - window + 1:index + 1]]
        return sum(closes, Decimal("0")) / Decimal(window)
