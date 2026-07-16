from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from qibao_api.gongbu.tdx_client import create_tdx_client


class FundamentalSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(pattern=r"^\d{6}$")
    observed_at: datetime
    report_period: date | None = None
    data_updated_on: date | None = None
    industry: str | None = None
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


def _date_or_none(value: Any) -> date | None:
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit() or text == "00000000":
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _industry_name_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text and not text.isdigit() else None


def _tdx_money_scale(payload: Mapping[str, Any]) -> Decimal | None:
    net_assets = _decimal_or_none(payload.get("jingzichan"))
    total_shares = _decimal_or_none(payload.get("zongguben"))
    book_value_per_share = _decimal_or_none(payload.get("meigujingzichan"))
    if (
        net_assets is None or total_shares is None or book_value_per_share is None
        or total_shares <= 0 or book_value_per_share <= 0
    ):
        return None
    ratio = net_assets / total_shares / book_value_per_share
    for decoded_ratio, scale in (
        (Decimal("10"), Decimal("0.1")),
        (Decimal("1"), Decimal("1")),
    ):
        if abs(ratio - decoded_ratio) <= decoded_ratio * Decimal("0.15"):
            return scale
    return None


def parse_tdx_finance(
    payload: Mapping[str, Any],
    symbol: str,
    observed_at: datetime,
) -> FundamentalSnapshot:
    money_scale = _tdx_money_scale(payload)
    net_profit_raw = _decimal_or_none(payload.get("jinglirun"))
    revenue_raw = _decimal_or_none(payload.get("zhuyingshouru"))
    net_assets_raw = _decimal_or_none(payload.get("jingzichan"))
    net_profit = (
        net_profit_raw * money_scale
        if net_profit_raw is not None and money_scale is not None else None
    )
    revenue = (
        revenue_raw * money_scale
        if revenue_raw is not None and money_scale is not None else None
    )
    net_assets = (
        net_assets_raw * money_scale
        if net_assets_raw is not None and money_scale is not None else None
    )
    total_shares = _decimal_or_none(payload.get("zongguben"))
    eps = (
        net_profit / total_shares
        if net_profit is not None and total_shares is not None and total_shares > 0
        else None
    )
    roe = (
        net_profit / net_assets * Decimal("100")
        if net_profit is not None and net_assets is not None and net_assets > 0
        else None
    )
    return FundamentalSnapshot(
        symbol=symbol,
        observed_at=observed_at,
        report_period=None,
        data_updated_on=_date_or_none(payload.get("updated_date")),
        industry=_industry_name_or_none(payload.get("industry")),
        eps=eps,
        roe=roe,
        net_profit=net_profit,
        revenue=revenue,
        book_value_per_share=_decimal_or_none(payload.get("meigujingzichan")),
        total_shares=total_shares,
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TdxFinanceSource:
    def __init__(
        self,
        client_factory: Callable[[], Any] = create_tdx_client,
        clock: Callable[[], datetime] = _utc_now,
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
