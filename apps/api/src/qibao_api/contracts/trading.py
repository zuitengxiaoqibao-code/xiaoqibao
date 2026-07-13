from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PaperAccount(BaseModel):
    account_id: str = Field(min_length=1, max_length=64)
    initial_cash: Decimal = Field(gt=0)
    cash: Decimal = Field(ge=0)
    total_equity: Decimal = Field(ge=0)
    exposure: Decimal = Field(ge=0, le=1)


class Position(BaseModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    shares: int = Field(ge=0)
    average_cost: Decimal = Field(ge=0)
    market_value: Decimal = Field(ge=0)


class OrderRequest(BaseModel):
    client_order_id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(pattern=r"^\d{6}$")
    side: Literal["buy", "sell"]
    shares: int = Field(gt=0, le=1_000_000)

    @field_validator("shares")
    @classmethod
    def require_board_lot(cls, shares: int) -> int:
        if shares % 100 != 0:
            raise ValueError("shares must be a multiple of 100")
        return shares


class Fill(BaseModel):
    fill_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    symbol: str = Field(pattern=r"^\d{6}$")
    side: Literal["buy", "sell"]
    shares: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    gross_amount: Decimal = Field(gt=0)
    commission: Decimal = Field(ge=0)
    slippage: Decimal = Field(ge=0)
    quote_source: str = Field(min_length=1)
    quote_observed_at: datetime
    risk_decision_id: str = Field(min_length=1)
    filled_at: datetime


class LedgerEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    amount: Decimal
    balance_after: Decimal = Field(ge=0)
    reason: Literal["deposit", "buy", "sell", "commission", "adjustment"]
    related_order_id: str | None = None
    related_fill_id: str | None = None
    created_at: datetime
