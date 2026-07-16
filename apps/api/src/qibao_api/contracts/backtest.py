from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BacktestRequest(BaseModel):
    strategy: Literal["sma_cross"] = "sma_cross"
    fast_window: int = Field(default=5, ge=2, le=120)
    slow_window: int = Field(default=20, ge=3, le=250)
    initial_cash: Decimal = Field(default=Decimal("100000"), gt=0)
    commission_rate: Decimal = Field(default=Decimal("0.0003"), ge=0, le=Decimal("0.01"))
    slippage_rate: Decimal = Field(default=Decimal("0.0005"), ge=0, le=Decimal("0.02"))

    @model_validator(mode="after")
    def validate_windows(self) -> "BacktestRequest":
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be lower than slow_window")
        return self


class Trade(BaseModel):
    side: Literal["buy", "sell"]
    signal_date: date
    trade_date: date
    price: Decimal
    shares: int = Field(gt=0)
    gross_amount: Decimal
    fees: Decimal


class EquityPoint(BaseModel):
    trade_date: date
    equity: Decimal
    cash: Decimal
    shares: int = Field(ge=0)
    market_value: Decimal


class PerformanceMetrics(BaseModel):
    annualized_volatility: Decimal = Field(ge=0)
    win_rate: Decimal = Field(ge=0, le=1)
    profit_loss_ratio: Decimal | None = Field(default=None, ge=0)
    turnover_rate: Decimal = Field(ge=0)
    closed_trade_count: int = Field(ge=0)


class BacktestSegmentResult(BaseModel):
    name: Literal["train", "validation", "out_of_sample"]
    start_date: date
    end_date: date
    bar_count: int = Field(gt=0)
    starting_equity: Decimal = Field(gt=0)
    ending_equity: Decimal = Field(gt=0)
    total_return: Decimal
    max_drawdown: Decimal = Field(ge=0, le=1)


class MarketRegimeResult(BaseModel):
    name: Literal["bull", "bear", "sideways"]
    bar_count: int = Field(ge=0)
    total_return: Decimal


class BacktestResult(BaseModel):
    symbol: str
    strategy: str
    initial_cash: Decimal
    ending_equity: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    total_cost: Decimal
    metrics: PerformanceMetrics
    segments: list[BacktestSegmentResult] = Field(default_factory=list)
    market_regimes: list[MarketRegimeResult] = Field(default_factory=list)
    trades: list[Trade]
    equity_curve: list[EquityPoint]
    warnings: list[str] = Field(default_factory=list)
