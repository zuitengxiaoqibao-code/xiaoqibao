from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import permutations

import pytest
from pydantic import ValidationError

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import RiskDecision
from qibao_api.xingbu.rules import (
    AccountDrawdownRule,
    DataFreshnessRule,
    IndustryConcentrationRule,
    LiquidityRule,
    MaxPositionRule,
    RiskContext,
    RiskEngine,
    TotalExposureRule,
)


NOW = datetime(2026, 7, 13, 9, 30, tzinfo=UTC)


def context(**updates: object) -> RiskContext:
    values: dict[str, object] = {
        "order_id": "order-1",
        "symbol": "600000",
        "asset": AssetKind.A_SHARE,
        "decided_at": NOW,
        "quote_observed_at": NOW - timedelta(seconds=30),
        "max_quote_age": timedelta(seconds=60),
        "projected_position": Decimal("0.20"),
        "max_position": Decimal("0.20"),
        "projected_total_exposure": Decimal("0.80"),
        "max_total_exposure": Decimal("0.80"),
        "projected_industry_exposure": Decimal("0.30"),
        "max_industry_exposure": Decimal("0.30"),
        "order_value": Decimal("100000"),
        "average_daily_turnover": Decimal("1000000"),
        "max_turnover_participation": Decimal("0.10"),
        "current_drawdown": Decimal("0.10"),
        "max_drawdown": Decimal("0.10"),
        "snapshot_reference": "snapshot://risk/order-1",
    }
    values.update(updates)
    return RiskContext(**values)


@pytest.mark.parametrize(
    ("rule", "at_limit", "over_limit", "outcome", "reason_code"),
    [
        (
            DataFreshnessRule(),
            {"quote_observed_at": NOW - timedelta(seconds=60)},
            {"quote_observed_at": NOW - timedelta(seconds=60, microseconds=1)},
            "reject",
            "quote_data_stale",
        ),
        (
            MaxPositionRule(),
            {"projected_position": Decimal("0.20")},
            {"projected_position": Decimal("0.2000001")},
            "reduce",
            "max_position_exceeded",
        ),
        (
            TotalExposureRule(),
            {"projected_total_exposure": Decimal("0.80")},
            {"projected_total_exposure": Decimal("0.8000001")},
            "reduce",
            "total_exposure_exceeded",
        ),
        (
            IndustryConcentrationRule(),
            {"projected_industry_exposure": Decimal("0.30")},
            {"projected_industry_exposure": Decimal("0.3000001")},
            "reduce",
            "industry_concentration_exceeded",
        ),
        (
            LiquidityRule(),
            {"order_value": Decimal("100000")},
            {"order_value": Decimal("100000.01")},
            "observe_only",
            "liquidity_limit_exceeded",
        ),
        (
            AccountDrawdownRule(),
            {"current_drawdown": Decimal("0.10")},
            {"current_drawdown": Decimal("0.1000001")},
            "reject",
            "account_drawdown_exceeded",
        ),
    ],
)
def test_rule_boundaries_are_inclusive_and_breaches_are_auditable(
    rule: object,
    at_limit: dict[str, object],
    over_limit: dict[str, object],
    outcome: str,
    reason_code: str,
) -> None:
    approved = rule.evaluate(context(**at_limit))
    breached = rule.evaluate(context(**over_limit))

    assert approved.outcome == "approve"
    assert breached.outcome == outcome
    assert breached.reason_code == reason_code
    assert breached.rule_id
    assert breached.rule_version
    assert breached.evidence == ("snapshot://risk/order-1",)
    assert breached.decided_at == NOW


def test_engine_result_is_independent_of_rule_order() -> None:
    rules = (
        DataFreshnessRule(),
        MaxPositionRule(),
        TotalExposureRule(),
        IndustryConcentrationRule(),
        LiquidityRule(),
        AccountDrawdownRule(),
    )
    breached = context(
        quote_observed_at=NOW - timedelta(minutes=2),
        projected_position=Decimal("0.21"),
        projected_total_exposure=Decimal("0.81"),
        projected_industry_exposure=Decimal("0.31"),
        order_value=Decimal("100001"),
        current_drawdown=Decimal("0.11"),
    )

    results = {
        RiskEngine(candidate_rules).review(breached).model_dump_json()
        for candidate_rules in permutations(rules)
    }

    assert len(results) == 1
    decision = RiskEngine(rules).review(breached)
    assert decision.outcome == "reject"
    assert decision.rule_id == "account_drawdown"


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        (("approve", "reduce"), "reduce"),
        (("reduce", "observe_only"), "observe_only"),
        (("observe_only", "reject"), "reject"),
    ],
)
def test_engine_uses_stable_outcome_precedence(outcomes: tuple[str, str], expected: str) -> None:
    class StubRule:
        def __init__(self, rule_id: str, outcome: str) -> None:
            self.rule_id = rule_id
            self.outcome = outcome

        def evaluate(self, risk_context: RiskContext):
            return RiskDecision(
                decision_id=f"{risk_context.order_id}:{self.rule_id}",
                order_id=risk_context.order_id,
                symbol=risk_context.symbol,
                asset=risk_context.asset,
                outcome=self.outcome,
                reason_code=f"{self.rule_id}_result",
                rule_id=self.rule_id,
                rule_version="test.1",
                evidence=(risk_context.snapshot_reference,),
                decided_at=risk_context.decided_at,
            )

    rules = tuple(StubRule(f"rule_{index}", value) for index, value in enumerate(outcomes))

    assert RiskEngine(rules).review(context()).outcome == expected


def test_context_accepts_only_a_share_orders() -> None:
    with pytest.raises(ValidationError):
        context(asset=AssetKind.CONVERTIBLE_BOND)
