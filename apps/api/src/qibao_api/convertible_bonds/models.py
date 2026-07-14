from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from qibao_api.contracts.convertible_bond import ConvertibleBondContract
from qibao_api.contracts.instruments import validate_convertible_bond_code
from qibao_api.contracts.market import AssetKind, DataQuality


class BondQuote(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    name: str
    price: Decimal | None = Field(default=None, gt=0)
    previous_close: Decimal = Field(gt=0)
    suspended: bool = False
    observed_at: datetime
    source: str
    quality: DataQuality
    raw_identity: str
    asset: Literal[AssetKind.CONVERTIBLE_BOND] = AssetKind.CONVERTIBLE_BOND

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return validate_convertible_bond_code(value)

    @field_validator("observed_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class BondClauseSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract: ConvertibleBondContract
    raw_payload: dict[str, Any]
    content_hash: str
    source: str
    fetched_at: datetime

    @field_validator("fetched_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must include a timezone")
        return value
