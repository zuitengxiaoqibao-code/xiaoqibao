from datetime import datetime, timezone
from decimal import Decimal

import pytest
from hypothesis import given, strategies as st
from pydantic import ValidationError

from qibao_api.convertible_bonds.candidates import (
    BondCandidate,
    BondCandidateFilter,
    filter_and_rank_candidates,
)
from qibao_api.convertible_bonds.metrics import EvidenceBackedClauseState
from qibao_api.convertible_bonds.risk import (
    BondRiskInput,
    BondRiskPolicy,
    evaluate_bond_risk,
)


NOW = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)


def clause(
    state: str = "not_triggered", bond_code: str = "113001"
) -> EvidenceBackedClauseState:
    return EvidenceBackedClauseState(
        bond_code=bond_code,
        state=state,
        clause_text="exchange announcement clause state",
        source="exchange-announcement",
        observed_at=NOW,
    )


def risk_input(**overrides: object) -> BondRiskInput:
    values = {
        "bond_code": "113001",
        "turnover_amount": Decimal("50000000"),
        "conversion_premium": Decimal("0.15"),
        "remaining_size": Decimal("12"),
        "remaining_days": 900,
        "strong_redemption": clause(),
    }
    values.update(overrides)
    if "strong_redemption" not in overrides:
        values["strong_redemption"] = clause(bond_code=str(values["bond_code"]))
    return BondRiskInput(**values)


def test_missing_turnover_amount_is_observe_only_and_names_the_missing_input() -> None:
    result = evaluate_bond_risk(risk_input(turnover_amount=None), BondRiskPolicy())

    assert result.outcome == "observe_only"
    assert result.reason_code == "bond_turnover_amount_missing"
    assert result.rule_id == "bond_liquidity"
    assert result.rule_version == "bond-risk.1"


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"turnover_amount": Decimal("999999")}, "bond_liquidity_below_minimum"),
        ({"conversion_premium": Decimal("0.51")}, "bond_conversion_premium_too_high"),
        ({"remaining_size": Decimal("0.49")}, "bond_remaining_size_too_small"),
        ({"remaining_days": 29}, "bond_maturity_too_near"),
        ({"strong_redemption": clause("triggered")}, "bond_strong_redemption_triggered"),
    ],
)
def test_each_bond_specific_risk_has_stable_reason_code(
    overrides: dict[str, object], reason_code: str
) -> None:
    result = evaluate_bond_risk(risk_input(**overrides), BondRiskPolicy())

    assert result.outcome == "exclude"
    assert result.reason_code == reason_code
    assert result.rule_version == "bond-risk.1"


def test_combination_uses_documented_priority_independent_of_input_field_order() -> None:
    inputs = {
        "conversion_premium": Decimal("0.9"),
        "turnover_amount": None,
        "remaining_size": Decimal("0.1"),
        "remaining_days": 1,
        "strong_redemption": clause("announced"),
    }
    forward = evaluate_bond_risk(risk_input(**inputs), BondRiskPolicy())
    reverse = evaluate_bond_risk(risk_input(**dict(reversed(list(inputs.items())))), BondRiskPolicy())

    assert forward == reverse
    assert forward.reason_code == "bond_strong_redemption_announced"
    assert forward.priority == 500


def test_strong_redemption_cannot_be_inferred_from_name_or_price() -> None:
    with pytest.raises(ValidationError):
        BondRiskInput(
            bond_code="113001",
            turnover_amount=Decimal("50000000"),
            conversion_premium=Decimal("0.15"),
            remaining_size=Decimal("12"),
            remaining_days=900,
            bond_name="XX redemption bond",
            bond_price=Decimal("130"),
        )


def candidate(code: str, **overrides: object) -> BondCandidate:
    values = {
        "bond_code": code,
        "bond_price": Decimal("110"),
        "turnover_amount": Decimal("50000000"),
        "conversion_premium": Decimal("0.15"),
        "remaining_size": Decimal("12"),
        "remaining_days": 900,
        "risk": evaluate_bond_risk(risk_input(bond_code=code), BondRiskPolicy()),
    }
    values.update(overrides)
    return BondCandidate(**values)


def test_candidate_input_forbids_a_share_research_and_score_fields() -> None:
    for field in ("research_card", "score", "ranking", "roe", "pe"):
        with pytest.raises(ValidationError):
            candidate("113001", **{field: 99})


def test_candidate_filter_and_ranking_use_only_bond_metrics_and_risk() -> None:
    first = candidate("113001", conversion_premium=Decimal("0.10"))
    second = candidate("118040", conversion_premium=Decimal("0.20"))
    excluded = candidate(
        "113002",
        risk=evaluate_bond_risk(
            risk_input(bond_code="113002", remaining_days=1), BondRiskPolicy()
        ),
    )

    ranked = filter_and_rank_candidates(
        [second, excluded, first], BondCandidateFilter(max_conversion_premium=Decimal("0.30"))
    )

    assert [item.bond_code for item in ranked] == ["113001", "118040"]


def test_empty_candidate_input_returns_empty_output() -> None:
    assert filter_and_rank_candidates([], BondCandidateFilter()) == []


@given(st.permutations(["113001", "113002", "113003"]))
def test_candidate_ranking_is_independent_of_arrival_order(codes: list[str]) -> None:
    premiums = {"113001": "0.1", "113002": "0.2", "113003": "0.3"}
    rows = [candidate(code, conversion_premium=Decimal(premiums[code])) for code in codes]

    assert [item.bond_code for item in filter_and_rank_candidates(rows)] == [
        "113001",
        "113002",
        "113003",
    ]


@given(st.decimals(min_value="0", max_value="1000000000", allow_nan=False))
def test_non_negative_turnover_is_preserved_exactly(value: Decimal) -> None:
    assert risk_input(turnover_amount=value).turnover_amount == value
