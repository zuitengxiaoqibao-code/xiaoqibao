from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, strategies as st
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


def test_decision_id_is_fixed_length_for_maximum_order_id() -> None:
    risk_context = context(order_id="o" * 128)

    first = MaxPositionRule().evaluate(risk_context)
    second = MaxPositionRule().evaluate(risk_context)

    assert first.decision_id == second.decision_id
    assert len(first.decision_id) <= 128


def test_future_quote_timestamp_is_rejected_with_machine_reason() -> None:
    decision = DataFreshnessRule().evaluate(
        context(quote_observed_at=NOW + timedelta(microseconds=1))
    )

    assert decision.outcome == "reject"
    assert decision.reason_code == "quote_timestamp_in_future"


RATIO_RULE_CASES = (
    (MaxPositionRule(), "projected_position", "max_position", "reduce"),
    (
        TotalExposureRule(),
        "projected_total_exposure",
        "max_total_exposure",
        "reduce",
    ),
    (
        IndustryConcentrationRule(),
        "projected_industry_exposure",
        "max_industry_exposure",
        "reduce",
    ),
    (AccountDrawdownRule(), "current_drawdown", "max_drawdown", "reject"),
)


@given(
    case=st.sampled_from(RATIO_RULE_CASES),
    limit=st.decimals(min_value="0", max_value="1000000", places=6),
    excess=st.decimals(min_value="0.000001", max_value="1000", places=6),
)
def test_ratio_rules_hold_at_limit_and_breach_above_it(
    case: tuple[object, str, str, str], limit: Decimal, excess: Decimal
) -> None:
    rule, value_field, limit_field, breach_outcome = case

    at_limit = rule.evaluate(context(**{value_field: limit, limit_field: limit}))
    above_limit = rule.evaluate(context(**{value_field: limit + excess, limit_field: limit}))

    assert at_limit.outcome == "approve"
    assert above_limit.outcome == breach_outcome


@given(
    turnover=st.decimals(min_value="0.01", max_value="1000000000000", places=2),
    participation=st.decimals(min_value="0", max_value="10", places=6),
    excess=st.decimals(min_value="0.01", max_value="1000000", places=2),
)
def test_liquidity_boundary_scales_with_turnover(
    turnover: Decimal, participation: Decimal, excess: Decimal
) -> None:
    limit = turnover * participation

    approved = LiquidityRule().evaluate(
        context(
            average_daily_turnover=turnover,
            max_turnover_participation=participation,
            order_value=limit,
        )
    )
    breached = LiquidityRule().evaluate(
        context(
            average_daily_turnover=turnover,
            max_turnover_participation=participation,
            order_value=limit + excess,
        )
    )

    assert approved.outcome == "approve"
    assert breached.outcome == "observe_only"


RULES = (
    DataFreshnessRule(),
    MaxPositionRule(),
    TotalExposureRule(),
    IndustryConcentrationRule(),
    LiquidityRule(),
    AccountDrawdownRule(),
)


@given(candidate_rules=st.permutations(RULES))
def test_engine_result_is_independent_of_rule_order(candidate_rules: list[object]) -> None:
    breached = context(
        quote_observed_at=NOW - timedelta(minutes=2),
        projected_position=Decimal("0.21"),
        projected_total_exposure=Decimal("0.81"),
        projected_industry_exposure=Decimal("0.31"),
        order_value=Decimal("100001"),
        current_drawdown=Decimal("0.11"),
    )

    decision = RiskEngine(tuple(candidate_rules)).review(breached)
    reference = RiskEngine(RULES).review(breached)

    assert decision == reference
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
