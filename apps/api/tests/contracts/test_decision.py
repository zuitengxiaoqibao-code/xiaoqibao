from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from qibao_api.contracts.decision import (
    AdviceCard,
    DecisionCycleSnapshot,
    EvidenceReference,
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


def test_advice_rejects_removed_simulated_plan_action() -> None:
    with pytest.raises(ValidationError):
        advice(action="simulated_plan")


def test_advice_contract_has_no_simulation_gate_fields() -> None:
    fields = AdviceCard.model_fields
    assert "simulation_gate" not in fields
    assert "simulation_plan_id" not in fields
