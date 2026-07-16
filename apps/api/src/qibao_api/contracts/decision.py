from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from qibao_api.contracts.instruments import validate_a_share_code, validate_convertible_bond_code
from qibao_api.contracts.market import AssetKind


DecisionPhase = Literal["premarket", "intraday", "postclose"]
AdviceAction = Literal["observe", "wait", "avoid", "invalidated"]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class EvidenceReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: NonBlank
    source: NonBlank
    snapshot_id: NonBlank
    summary: NonBlank
    observed_at: AwareDatetime


class DecisionCycleSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: NonBlank
    trading_date: date
    phase: DecisionPhase
    sequence: int = Field(ge=1)
    generated_at: AwareDatetime
    window_start: AwareDatetime
    window_end: AwareDatetime
    market_state: Literal["strong", "range", "weak", "insufficient_data"]
    data_quality: Literal["ready", "partial", "blocked"]
    source_snapshot_ids: tuple[NonBlank, ...]
    source_observed_at: tuple[AwareDatetime, ...]
    candidate_snapshot_id: str | None
    news_event_ids: tuple[NonBlank, ...]
    risk_event_ids: tuple[NonBlank, ...]
    input_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_snapshot_id: str | None
    status: Literal["ready", "partial", "blocked"]
    ai_status: Literal["ready", "unavailable", "not_requested"]

    @model_validator(mode="after")
    def validate_window_and_chain(self) -> "DecisionCycleSnapshot":
        if not self.window_start < self.window_end <= self.generated_at:
            raise ValueError("window must satisfy start < end <= generated time")
        if any(observed > self.window_end for observed in self.source_observed_at):
            raise ValueError("source observation is after window end")
        if self.sequence == 1 and self.previous_snapshot_id is not None:
            raise ValueError("first sequence cannot have a previous snapshot")
        if self.sequence > 1 and not self.previous_snapshot_id:
            raise ValueError("later sequence requires a previous snapshot")
        for values in (self.source_snapshot_ids, self.news_event_ids, self.risk_event_ids):
            if len(values) != len(set(values)):
                raise ValueError("snapshot reference ids must be unique")
        return self


class AdviceCard(BaseModel):
    model_config = ConfigDict(frozen=True)

    advice_id: NonBlank
    snapshot_id: NonBlank
    asset: AssetKind
    symbol: str
    horizon: Literal["intraday", "swing"]
    observation_state: NonBlank
    action: AdviceAction
    conclusion: NonBlank
    confidence: Decimal = Field(ge=0, le=1)
    supporting_evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    contrary_evidence: tuple[EvidenceReference, ...]
    risks: tuple[NonBlank, ...] = Field(min_length=1)
    invalidation_conditions: tuple[NonBlank, ...] = Field(min_length=1)
    plain_language_explanation: str | None = None
    quantitative_result: dict[str, Decimal | str | None]
    ai_interpretation_id: str | None = None
    risk_decision_id: str | None = None
    previous_advice_id: str | None = None
    changed_fields: tuple[NonBlank, ...] = ()
    strategy_version: NonBlank
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_asset(self) -> "AdviceCard":
        if self.asset == AssetKind.A_SHARE:
            validate_a_share_code(self.symbol)
        else:
            validate_convertible_bond_code(self.symbol)
        return self


class DecisionCycleAggregate(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot: DecisionCycleSnapshot
    advice: tuple[AdviceCard, ...]
