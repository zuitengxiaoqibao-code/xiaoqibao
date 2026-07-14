from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from qibao_api.contracts.instruments import validate_convertible_bond_code


class RemainingTerm(BaseModel):
    model_config = ConfigDict(frozen=True)

    days: int = Field(ge=0)
    years: Decimal = Field(ge=0)
    day_count: Literal["actual/365"] = "actual/365"


class ConvertibleBondMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversion_value: Decimal | None
    conversion_premium: Decimal | None
    pure_bond_premium: Decimal | None
    remaining_term: RemainingTerm
    remaining_size: Decimal = Field(ge=0)


class EvidenceBackedClauseState(BaseModel):
    """Strong-redemption state reported by an explicit, timestamped clause source."""

    model_config = ConfigDict(frozen=True)

    bond_code: str
    state: Literal["unknown", "not_triggered", "triggered", "announced", "completed"]
    clause_text: str | None = None
    source: str = Field(min_length=1)
    observed_at: datetime

    @field_validator("bond_code")
    @classmethod
    def validate_bond_code(cls, value: str) -> str:
        return validate_convertible_bond_code(value)

    @field_validator("clause_text", "source")
    @classmethod
    def reject_blank_evidence(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("clause evidence must not be blank")
        return value

    @field_validator("observed_at")
    @classmethod
    def require_aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value

    @model_validator(mode="after")
    def require_text_for_known_state(self):
        if self.state != "unknown" and self.clause_text is None:
            raise ValueError("known strong-redemption state requires clause evidence")
        return self


def _require_positive(value: Decimal, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def conversion_value(
    par_value: Decimal,
    conversion_price: Decimal,
    stock_price: Decimal | None,
) -> Decimal | None:
    _require_positive(par_value, "par_value")
    _require_positive(conversion_price, "conversion_price")
    if stock_price is None:
        return None
    _require_positive(stock_price, "stock_price")
    return par_value / conversion_price * stock_price


def conversion_premium(
    bond_price: Decimal | None,
    calculated_conversion_value: Decimal | None,
) -> Decimal | None:
    if bond_price is None or calculated_conversion_value is None:
        return None
    _require_positive(bond_price, "bond_price")
    _require_positive(calculated_conversion_value, "conversion_value")
    return (bond_price - calculated_conversion_value) / calculated_conversion_value


def pure_bond_premium(
    bond_price: Decimal | None,
    pure_bond_value: Decimal | None,
) -> Decimal | None:
    if bond_price is None or pure_bond_value is None:
        return None
    _require_positive(bond_price, "bond_price")
    _require_positive(pure_bond_value, "pure_bond_value")
    return (bond_price - pure_bond_value) / pure_bond_value


def remaining_term(as_of: date, maturity: date) -> RemainingTerm:
    days = (maturity - as_of).days
    if days < 0:
        raise ValueError("maturity must not be before as_of")
    return RemainingTerm(days=days, years=Decimal(days) / Decimal("365"))


def calculate_metrics(
    *,
    par_value: Decimal,
    conversion_price: Decimal,
    stock_price: Decimal | None,
    bond_price: Decimal | None,
    pure_bond_value: Decimal | None,
    as_of: date,
    maturity: date,
    remaining_size: Decimal,
    bond_suspended: bool = False,
    stock_suspended: bool = False,
) -> ConvertibleBondMetrics:
    if remaining_size < 0:
        raise ValueError("remaining_size must not be negative")

    effective_stock_price = None if stock_suspended else stock_price
    calculated_conversion_value = conversion_value(
        par_value, conversion_price, effective_stock_price
    )
    effective_bond_price = None if bond_suspended else bond_price
    return ConvertibleBondMetrics(
        conversion_value=calculated_conversion_value,
        conversion_premium=conversion_premium(
            effective_bond_price, calculated_conversion_value
        ),
        pure_bond_premium=pure_bond_premium(effective_bond_price, pure_bond_value),
        remaining_term=remaining_term(as_of, maturity),
        remaining_size=remaining_size,
    )


def format_decimal(value: Decimal, *, places: int) -> str:
    if places < 0:
        raise ValueError("places must not be negative")
    quantum = Decimal("1").scaleb(-places)
    return format(value.quantize(quantum, rounding=ROUND_HALF_UP), f".{places}f")
