import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from qibao_api.contracts.decision import SimulationPlan


class QuantitativeLevels(BaseModel):
    model_config = ConfigDict(frozen=True)

    watch_price_low: Decimal = Field(gt=0)
    watch_price_high: Decimal = Field(gt=0)
    stop_loss: Decimal = Field(gt=0)
    take_profit: tuple[Decimal, ...] = Field(max_length=2)
    tranches: tuple[Decimal, ...] = Field(max_length=3)
    max_position: Decimal = Field(gt=0, le=1)
    calculated_at: AwareDatetime
    calculation_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_levels(self) -> "QuantitativeLevels":
        if self.watch_price_low > self.watch_price_high:
            raise ValueError("watch price low must not exceed high")
        if not self.take_profit or any(value <= 0 for value in self.take_profit):
            raise ValueError("take-profit prices must be positive")
        if not self.tranches or any(value <= 0 for value in self.tranches):
            raise ValueError("tranches must be positive")
        if sum(self.tranches, Decimal()) > 1:
            raise ValueError("tranches must sum to at most one")
        if sum(self.tranches, Decimal()) > self.max_position:
            raise ValueError("tranches must sum to at most max position")
        return self


class SimulationGateContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    quote_state: Literal["ready", "blocked"]
    compliance_state: Literal["ready", "blocked"]
    evidence_state: Literal["ready", "blocked"]
    risk_state: Literal["approve", "reject"]
    advice_id: str = Field(min_length=1)
    risk_decision_id: str | None
    compliance_snapshot_id: str | None
    levels: QuantitativeLevels | None

    def failed_gate_reasons(self) -> tuple[str, ...]:
        reasons = []
        for field in ("quote", "compliance", "evidence"):
            if getattr(self, f"{field}_state") != "ready":
                reasons.append(f"{field}_blocked")
        if self.risk_state != "approve":
            reasons.append("risk_rejected")
        if not self.risk_decision_id:
            reasons.append("risk_reference_missing")
        if not self.compliance_snapshot_id:
            reasons.append("compliance_reference_missing")
        if self.levels is None:
            reasons.append("quantitative_levels_missing")
        return tuple(reasons)


class SimulationPlanBuilder:
    def __init__(self, *, now: datetime, max_level_age: timedelta = timedelta(minutes=5)) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        self.now = now
        self.max_level_age = max_level_age

    def build(self, context: SimulationGateContext) -> SimulationPlan | None:
        if context.failed_gate_reasons():
            return None
        levels = context.levels
        assert levels is not None
        if levels.calculated_at > self.now:
            self._levels_error(levels, "future", "quantitative levels are from the future")
        if self.now - levels.calculated_at > self.max_level_age:
            self._levels_error(levels, "stale", "quantitative levels are stale")
        risk_id = context.risk_decision_id
        compliance_id = context.compliance_snapshot_id
        assert risk_id is not None and compliance_id is not None
        valid_from = levels.calculated_at
        valid_until = levels.calculated_at + self.max_level_age
        identity = json.dumps({
            "advice_id": context.advice_id,
            "risk_decision_id": risk_id,
            "compliance_snapshot_id": compliance_id,
            "levels": levels.model_dump(mode="json"),
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
        }, sort_keys=True, separators=(",", ":"))
        plan_id = f"simulation-{hashlib.sha256(identity.encode()).hexdigest()[:24]}"
        return SimulationPlan(
            plan_id=plan_id, advice_id=context.advice_id, risk_decision_id=risk_id,
            compliance_snapshot_id=compliance_id,
            watch_price_low=levels.watch_price_low, watch_price_high=levels.watch_price_high,
            stop_loss=levels.stop_loss, take_profit=levels.take_profit,
            tranches=levels.tranches, max_position=levels.max_position,
            invalidation_conditions=("quantitative_levels_changed",),
            valid_from=valid_from, valid_until=valid_until,
            strategy_version=levels.calculation_version,
            risk_version=risk_id, compliance_version=compliance_id,
        )

    @staticmethod
    def _levels_error(levels: QuantitativeLevels, code: str, message: str) -> None:
        raise ValidationError.from_exception_data(
            "QuantitativeLevels",
            [{
                "type": PydanticCustomError(code, message),
                "loc": ("levels", "calculated_at"),
                "input": levels.calculated_at,
            }],
        )
