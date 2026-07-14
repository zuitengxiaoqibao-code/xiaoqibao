from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FACTOR_VERSION = "a-share-factors-v1"


class FactorSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(pattern=r"^\d{6}$")
    as_of: date
    close: Decimal = Field(gt=0)
    return_5d: Decimal
    return_20d: Decimal
    distance_ma20: Decimal
    volume_ratio_5_20: Decimal = Field(ge=0)
    volatility_20d: Decimal = Field(ge=0)
    drawdown_60d: Decimal = Field(le=0)
    liquidity_amount_20d: Decimal = Field(ge=0)
    factor_version: Literal["a-share-factors-v1"] = FACTOR_VERSION
    source: str = Field(min_length=1)


class CandidateEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(pattern=r"^\d{6}$")
    horizon: Literal["short_term", "swing"]
    score: Decimal = Field(ge=-30, le=90)
    score_breakdown: dict[str, Decimal]
    factor_snapshot: FactorSnapshot


class CandidateExclusion(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(pattern=r"^\d{6}$")
    reason_code: Literal["insufficient_liquidity", "invalid_history"]
    observed_value: Decimal | None = None
    threshold: Decimal | None = None
    detail: str | None = None


class CandidateBoard(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: Literal["a_share"] = "a_share"
    universe_status: Literal["ready", "empty"] = "ready"
    snapshot_id: str | None = None
    input_snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    as_of: date
    factor_version: Literal["a-share-factors-v1"] = FACTOR_VERSION
    short_term: list[CandidateEntry]
    swing: list[CandidateEntry]
    exclusions: list[CandidateExclusion] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def derive_empty_universe(cls, value):
        if isinstance(value, dict) and "universe_status" not in value:
            value = dict(value)
            value["universe_status"] = (
                "empty" if not value.get("short_term") and not value.get("swing") else "ready"
            )
        return value

    @model_validator(mode="after")
    def require_one_frozen_factor_date(self) -> "CandidateBoard":
        entries = [*self.short_term, *self.swing]
        if any(item.factor_snapshot.as_of != self.as_of for item in entries):
            raise ValueError("candidate snapshots must match board as_of")
        return self
