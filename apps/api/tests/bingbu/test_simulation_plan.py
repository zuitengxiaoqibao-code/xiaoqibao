from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from qibao_api.bingbu.simulation_plan import (
    QuantitativeLevels, SimulationGateContext, SimulationPlanBuilder,
)


NOW = datetime(2026, 7, 14, 2, 30, tzinfo=UTC)


def levels(**updates):
    values = dict(
        watch_price_low=Decimal("10.10"), watch_price_high=Decimal("10.30"),
        stop_loss=Decimal("9.80"), take_profit=(Decimal("10.80"), Decimal("11.20")),
        tranches=(Decimal("0.2"), Decimal("0.3")), max_position=Decimal("0.5"),
        calculated_at=NOW, calculation_version="levels-v1",
    )
    values.update(updates)
    return QuantitativeLevels(**values)


def context(**updates):
    values = dict(
        quote_state="ready", compliance_state="ready", evidence_state="ready",
        risk_state="approve", advice_id="advice-1", risk_decision_id="risk-1",
        compliance_snapshot_id="compliance-1", levels=levels(),
    )
    values.update(updates)
    return SimulationGateContext(**values)


@pytest.mark.parametrize("updates", [
    {"quote_state": "blocked"}, {"compliance_state": "blocked"},
    {"evidence_state": "blocked"}, {"risk_state": "reject"},
    {"risk_decision_id": None}, {"compliance_snapshot_id": None}, {"levels": None},
])
def test_each_gate_independently_blocks_plan(updates) -> None:
    assert SimulationPlanBuilder(now=NOW).build(context(**updates)) is None


def test_plan_copies_levels_exactly_and_binds_versions() -> None:
    plan = SimulationPlanBuilder(now=NOW).build(context())
    assert plan is not None
    assert (plan.watch_price_low, plan.watch_price_high, plan.stop_loss) == (
        Decimal("10.10"), Decimal("10.30"), Decimal("9.80")
    )
    assert plan.take_profit == (Decimal("10.80"), Decimal("11.20"))
    assert plan.tranches == (Decimal("0.2"), Decimal("0.3"))
    assert plan.max_position == Decimal("0.5")
    assert plan.strategy_version == "levels-v1"
    assert plan.risk_version == "risk-1"
    assert plan.compliance_version == "compliance-1"


def test_invalid_and_stale_levels_raise_validation_error() -> None:
    with pytest.raises(ValidationError):
        levels(watch_price_low=Decimal("11"), watch_price_high=Decimal("10"))
    with pytest.raises(ValidationError, match="stale"):
        SimulationPlanBuilder(now=NOW + timedelta(minutes=6)).build(context())
