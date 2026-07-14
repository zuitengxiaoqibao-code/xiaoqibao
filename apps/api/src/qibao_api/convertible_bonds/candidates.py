from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from qibao_api.contracts.instruments import validate_convertible_bond_code
from qibao_api.convertible_bonds.risk import BondRiskResult


class BondCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bond_code: str
    bond_price: Decimal = Field(gt=0)
    turnover_amount: Decimal | None = Field(default=None, ge=0)
    conversion_premium: Decimal | None
    remaining_size: Decimal = Field(ge=0)
    remaining_days: int = Field(ge=0)
    risk: BondRiskResult

    @field_validator("bond_code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return validate_convertible_bond_code(value)


class BondCandidateFilter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_conversion_premium: Decimal | None = None
    min_turnover_amount: Decimal | None = Field(default=None, ge=0)
    min_remaining_size: Decimal | None = Field(default=None, ge=0)
    min_remaining_days: int | None = Field(default=None, ge=0)


def filter_and_rank_candidates(
    candidates: list[BondCandidate], filters: BondCandidateFilter | None = None
) -> list[BondCandidate]:
    selected: list[BondCandidate] = []
    filters = filters or BondCandidateFilter()
    for item in candidates:
        if item.risk.outcome == "exclude":
            continue
        if filters.max_conversion_premium is not None and (
            item.conversion_premium is None or item.conversion_premium > filters.max_conversion_premium
        ):
            continue
        if filters.min_turnover_amount is not None and (
            item.turnover_amount is None or item.turnover_amount < filters.min_turnover_amount
        ):
            continue
        if filters.min_remaining_size is not None and item.remaining_size < filters.min_remaining_size:
            continue
        if filters.min_remaining_days is not None and item.remaining_days < filters.min_remaining_days:
            continue
        selected.append(item)
    return sorted(
        selected,
        key=lambda item: (
            item.risk.priority,
            item.conversion_premium is None,
            item.conversion_premium or Decimal(0),
            -item.turnover_amount if item.turnover_amount is not None else Decimal(0),
            item.bond_code,
        ),
    )
