from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from qibao_api.contracts.decision import (
    AdviceCard,
    DecisionCycleSnapshot,
    EvidenceReference,
    SimulationPlan,
)


NOW = datetime(2026, 7, 15, 9, 20, tzinfo=timezone(timedelta(hours=8)))


def evidence() -> EvidenceReference:
    return EvidenceReference(
        evidence_id="quote-1", source="tencent", snapshot_id="quote-snapshot-1",
        summary="price snapshot", observed_at=NOW - timedelta(minutes=2),
    )


def advice(**updates: object) -> AdviceCard:
    values = dict(
        advice_id="advice-1", snapshot_id="cycle-1", asset="a_share",
        symbol="600000", horizon="intraday", observation_state="watching",
        action="observe", conclusion="wait for confirmation", confidence=Decimal("0.62"),
        supporting_evidence=(evidence(),), contrary_evidence=(), risks=("volume risk",),
        invalidation_conditions=("breaks support",), quantitative_result={},
        strategy_version="decision-v1", created_at=NOW,
    )
    values.update(updates)
    return AdviceCard(**values)


def plan(**updates: object) -> SimulationPlan:
    values = dict(
        plan_id="plan-1", advice_id="advice-1", risk_decision_id="risk-1",
        compliance_snapshot_id="compliance-1", watch_price_low="10.00",
        watch_price_high="10.20", stop_loss="9.70", take_profit=("10.60", "11.00"),
        tranches=("0.3", "0.3"), max_position="0.6",
        invalidation_conditions=("breaks support",), valid_from=NOW,
        valid_until=NOW + timedelta(hours=1), strategy_version="decision-v1",
        risk_version="risk-v1", compliance_version="compliance-v1",
    )
    values.update(updates)
    return SimulationPlan(**values)


def test_advice_requires_risk_and_invalidation_disclosures() -> None:
    with pytest.raises(ValidationError):
        advice(risks=())
    with pytest.raises(ValidationError):
        advice(invalidation_conditions=())


@pytest.mark.parametrize(
    ("asset", "symbol"),
    [("a_share", "118040"), ("convertible_bond", "600000")],
)
def test_advice_validates_symbol_for_asset(asset: str, symbol: str) -> None:
    with pytest.raises(ValidationError):
        advice(asset=asset, symbol=symbol)


def test_cycle_rejects_inputs_after_window_end() -> None:
    with pytest.raises(ValidationError, match="after window end"):
        DecisionCycleSnapshot(
            snapshot_id="cycle-1", trading_date=date(2026, 7, 15), phase="premarket",
            sequence=1, generated_at=NOW, window_start=NOW - timedelta(hours=1),
            window_end=NOW - timedelta(minutes=1), market_state="range", data_quality="ready",
            source_snapshot_ids=("quote-snapshot-1",), source_observed_at=(NOW,),
            candidate_snapshot_id=None, news_event_ids=(), risk_event_ids=(),
            input_snapshot_hash="a" * 64, previous_snapshot_id=None, status="ready",
            ai_status="not_requested",
        )


def test_simulation_plan_enforces_numeric_limits() -> None:
    with pytest.raises(ValidationError):
        plan(watch_price_low="10.30")
    with pytest.raises(ValidationError):
        plan(take_profit=("10.5", "11", "12"))
    with pytest.raises(ValidationError):
        plan(tranches=("0.4", "0.4", "0.4"))
    with pytest.raises(ValidationError):
        plan(max_position="0")
    with pytest.raises(ValidationError):
        plan(tranches=("0.4", "0.3"), max_position="0.6")


def test_simulated_advice_requires_gate_references() -> None:
    with pytest.raises(ValidationError):
        advice(action="simulated_plan", simulation_plan_id="plan-1")
    with pytest.raises(ValidationError):
        advice(simulation_plan_id="plan-1")
    with pytest.raises(ValidationError):
        advice(action="simulated_plan", simulation_plan_id="plan-1", risk_decision_id="risk-1")
