from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from qibao_api.contracts.instruments import (
    validate_a_share_code,
    validate_convertible_bond_code,
)
from qibao_api.contracts.market import AssetKind


class ClauseDates(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversion_start: date
    redemption_start: date | None = None
    put_back_start: date | None = None


class ConvertibleBondContract(BaseModel):
    """Immutable terms observed for one convertible bond at a specific time."""

    model_config = ConfigDict(frozen=True)

    bond_code: str
    linked_stock: str
    conversion_price: Decimal = Field(gt=0)
    maturity: date
    remaining_size: Decimal = Field(ge=0)
    clause_dates: ClauseDates
    as_of: datetime
    asset: Literal[AssetKind.CONVERTIBLE_BOND] = AssetKind.CONVERTIBLE_BOND

    @field_validator("bond_code")
    @classmethod
    def validate_bond_code(cls, value: str) -> str:
        return validate_convertible_bond_code(value)

    @field_validator("linked_stock")
    @classmethod
    def validate_linked_stock(cls, value: str) -> str:
        return validate_a_share_code(value)

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        return value

    @model_validator(mode="after")
    def require_clause_dates_by_maturity(self) -> "ConvertibleBondContract":
        clause_dates = (
            self.clause_dates.conversion_start,
            self.clause_dates.redemption_start,
            self.clause_dates.put_back_start,
        )
        if any(value is not None and value > self.maturity for value in clause_dates):
            raise ValueError("clause dates must not be after maturity")
        return self
