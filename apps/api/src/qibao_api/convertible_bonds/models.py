from datetime import datetime
from decimal import Decimal
from typing import Literal

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
    turnover_amount: Decimal | None = Field(default=None, ge=0)
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
    raw_payload: bytes
    content_hash: str
    source: str
    fetched_at: datetime
    parser_version: str
    strong_redemption: "StrongRedemptionEvidence" = Field(default_factory=lambda: StrongRedemptionEvidence())

    @field_validator("fetched_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must include a timezone")
        return value


class StrongRedemptionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    state: Literal["unknown", "triggered", "announced", "completed"] = "unknown"
    clause_present: bool = False
    evidence_fields: dict[str, str] = Field(default_factory=dict)
    clause_text: str | None = None


class BondValuation(BaseModel):
    model_config = ConfigDict(frozen=True)
    bond_code: str
    observed_at: datetime
    pure_bond_value: Decimal = Field(gt=0)
    provider_conversion_value: Decimal | None = None
    provider_conversion_premium: Decimal | None = None
    provider_pure_bond_premium: Decimal | None = None
    close: Decimal | None = None
    conversion_price: Decimal | None = None
    source: str = "eastmoney"
    raw_identity: str
