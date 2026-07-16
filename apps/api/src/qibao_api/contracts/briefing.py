from datetime import date
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from qibao_api.contracts.instruments import (
    validate_a_share_code,
    validate_convertible_bond_code,
)
from qibao_api.contracts.market import AssetKind


NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SnapshotHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
BriefingPhase = Literal["premarket", "intraday", "postclose"]


class PostcloseContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_outcome_ids: tuple[NonBlank, ...] = ()
    error_codes: tuple[NonBlank, ...] = ()
    risk_event_ids: tuple[NonBlank, ...] = ()


class BriefingSections(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_event_ids: tuple[NonBlank, ...] = ()
    risk_event_ids: tuple[NonBlank, ...] = ()
    watchlist: tuple[tuple[AssetKind, str], ...] = ()
    signal_outcome_ids: tuple[NonBlank, ...] = ()
    error_codes: tuple[NonBlank, ...] = ()
    next_day_observations: tuple[NonBlank, ...] = ()

    @field_validator("watchlist")
    @classmethod
    def validate_watchlist(
        cls, values: tuple[tuple[AssetKind, str], ...]
    ) -> tuple[tuple[AssetKind, str], ...]:
        for asset, symbol in values:
            if asset is AssetKind.A_SHARE:
                validate_a_share_code(symbol)
            else:
                validate_convertible_bond_code(symbol)
        if len(set(values)) != len(values):
            raise ValueError("watchlist entries must be unique")
        return values


class DailyBriefing(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: NonBlank
    trading_date: date
    phase: BriefingPhase
    generated_at: AwareDatetime
    window_start: AwareDatetime
    window_end: AwareDatetime
    event_ids: tuple[NonBlank, ...] = ()
    interpretation_ids: tuple[NonBlank, ...] = ()
    input_snapshot_hash: SnapshotHash
    sections: BriefingSections

    @model_validator(mode="after")
    def validate_frozen_window(self) -> "DailyBriefing":
        if self.window_end <= self.window_start:
            raise ValueError("briefing window must have positive duration")
        if self.generated_at < self.window_end:
            raise ValueError("briefing cannot be generated before its window ends")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("briefing event ids must be unique")
        if len(set(self.interpretation_ids)) != len(self.interpretation_ids):
            raise ValueError("briefing interpretation ids must be unique")
        if not set(self.sections.policy_event_ids).issubset(set(self.event_ids)):
            raise ValueError("policy section references events outside frozen inputs")
        return self
