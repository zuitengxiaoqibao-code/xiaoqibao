from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from qibao_api.gongbu.tdx_client import create_tdx_client


class FundamentalSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(pattern=r"^\d{6}$")
    observed_at: datetime
    eps: Decimal | None = None
    roe: Decimal | None = None
    net_profit: Decimal | None = None
    revenue: Decimal | None = None
    book_value_per_share: Decimal | None = None
    total_shares: Decimal | None = Field(default=None, ge=0)
    source: str


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "" or value == "--":
        return None
    if isinstance(value, float) and not isfinite(value):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def parse_tdx_finance(
    payload: Mapping[str, Any],
    symbol: str,
    observed_at: datetime,
) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        observed_at=observed_at,
        eps=_decimal_or_none(payload.get("eps")),
        roe=_decimal_or_none(payload.get("roe")),
        net_profit=_decimal_or_none(payload.get("profit")),
        revenue=_decimal_or_none(payload.get("income")),
        book_value_per_share=_decimal_or_none(payload.get("bvps")),
        total_shares=_decimal_or_none(payload.get("zongguben")),
        source="mootdx-finance",
    )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "empty") and value.empty:
        return {}
    if hasattr(value, "iloc"):
        row = value.iloc[0]
        if hasattr(row, "to_dict"):
            return row.to_dict()
    if hasattr(value, "to_dict"):
        result = value.to_dict()
        if isinstance(result, Mapping):
            return result
    raise ValueError("unsupported mootdx finance response")


class TdxFinanceSource:
    def __init__(
        self,
        client_factory: Callable[[], Any] = create_tdx_client,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.client_factory = client_factory
        self.clock = clock

    def fetch(self, symbol: str) -> FundamentalSnapshot:
        client = self.client_factory()
        try:
            payload = client.finance(symbol=symbol)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        mapping = _as_mapping(payload)
        if not mapping:
            raise ValueError("mootdx finance response is empty")
        return parse_tdx_finance(mapping, symbol, self.clock())
