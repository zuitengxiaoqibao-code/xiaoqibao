from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

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


def test_missing_conversion_premium_is_observe_only() -> None:
    result = evaluate_bond_risk(risk_input(conversion_premium=None), BondRiskPolicy())

    assert result.outcome == "observe_only"
    assert result.reason_code == "bond_conversion_premium_missing"


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


def test_exclude_outcome_always_beats_higher_priority_observe_only() -> None:
    result = evaluate_bond_risk(
        risk_input(strong_redemption=clause("unknown"), remaining_size=Decimal("0.1")),
        BondRiskPolicy(),
    )

    assert result.outcome == "exclude"
    assert result.reason_code == "bond_remaining_size_too_small"


@given(
    st.sampled_from(
        [
            {"remaining_days": 1},
            {"remaining_size": Decimal("0.1")},
            {"conversion_premium": Decimal("0.9")},
            {"turnover_amount": Decimal("1")},
        ]
    )
)
def test_unknown_strong_redemption_never_masks_an_exclusion(
    exclusion: dict[str, object],
) -> None:
    result = evaluate_bond_risk(
        risk_input(strong_redemption=clause("unknown"), **exclusion), BondRiskPolicy()
    )

    assert result.outcome == "exclude"


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
    evidence = clause(bond_code=code)
    values = {
        "bond_code": code,
        "bond_price": Decimal("110"),
        "turnover_amount": Decimal("50000000"),
        "conversion_premium": Decimal("0.15"),
        "remaining_size": Decimal("12"),
        "remaining_days": 900,
        "strong_redemption": evidence,
    }
    values.update(overrides)
    if "risk" not in overrides:
        values["risk"] = evaluate_bond_risk(
            risk_input(
                bond_code=code,
                turnover_amount=values["turnover_amount"],
                conversion_premium=values["conversion_premium"],
                remaining_size=values["remaining_size"],
                remaining_days=values["remaining_days"],
                strong_redemption=values["strong_redemption"],
            ),
            BondRiskPolicy(),
        )
    return BondCandidate(**values)


def test_candidate_input_forbids_a_share_research_and_score_fields() -> None:
    for field in ("research_card", "score", "ranking", "roe", "pe"):
        with pytest.raises(ValidationError):
            candidate("113001", **{field: 99})


def test_risk_result_is_bound_to_bond_asset_and_canonical_input_snapshot() -> None:
    value = risk_input()
    first = evaluate_bond_risk(value, BondRiskPolicy())
    second = evaluate_bond_risk(value, BondRiskPolicy())

    assert first.bond_code == "113001"
    assert first.asset.value == "convertible_bond"
    assert first.input_fingerprint == second.input_fingerprint
    assert len(first.input_fingerprint) == 64


@given(
    value=st.decimals(
        min_value="-1000", max_value="1000", allow_nan=False, allow_infinity=False
    ),
    trailing_zeros=st.integers(min_value=1, max_value=8),
)
def test_fingerprint_normalizes_semantically_equal_decimal_encodings(
    value: Decimal, trailing_zeros: int
) -> None:
    decimal_tuple = value.as_tuple()
    equivalent = Decimal(
        (
            decimal_tuple.sign,
            decimal_tuple.digits + (0,) * trailing_zeros,
            decimal_tuple.exponent - trailing_zeros,
        )
    )

    first = evaluate_bond_risk(risk_input(conversion_premium=value), BondRiskPolicy())
    second = evaluate_bond_risk(
        risk_input(conversion_premium=equivalent), BondRiskPolicy()
    )

    assert value == equivalent
    assert first.input_fingerprint == second.input_fingerprint


def test_fingerprint_normalizes_decimal_zero_and_exponent_forms() -> None:
    pairs = [(Decimal("0"), Decimal("-0.000")), (Decimal("1E+2"), Decimal("100.00"))]

    for first_value, second_value in pairs:
        first = evaluate_bond_risk(
            risk_input(turnover_amount=first_value), BondRiskPolicy()
        )
        second = evaluate_bond_risk(
            risk_input(turnover_amount=second_value), BondRiskPolicy()
        )
        assert first.input_fingerprint == second.input_fingerprint


def test_fingerprint_preserves_digits_beyond_decimal_context_precision() -> None:
    first_value = Decimal("0.1234567890123456789012345678901234567891")
    second_value = Decimal("0.1234567890123456789012345678901234567892")

    first = evaluate_bond_risk(
        risk_input(conversion_premium=first_value), BondRiskPolicy()
    )
    second = evaluate_bond_risk(
        risk_input(conversion_premium=second_value), BondRiskPolicy()
    )

    assert first.input_fingerprint != second.input_fingerprint


def test_fingerprint_is_independent_of_active_decimal_context_precision() -> None:
    value = risk_input(
        conversion_premium=Decimal("0.1234567890123456789012345678901234567891")
    )
    baseline = evaluate_bond_risk(value, BondRiskPolicy()).input_fingerprint

    with localcontext() as context:
        context.prec = 5
        under_low_precision = evaluate_bond_risk(
            value, BondRiskPolicy()
        ).input_fingerprint

    assert under_low_precision == baseline


def test_fingerprint_normalizes_same_instant_to_utc_fixed_format() -> None:
    utc_evidence = clause().model_copy(
        update={"observed_at": datetime(2026, 7, 14, 1, 30, tzinfo=timezone.utc)}
    )
    china_evidence = clause().model_copy(
        update={
            "observed_at": datetime(
                2026, 7, 14, 9, 30, tzinfo=timezone(timedelta(hours=8))
            )
        }
    )

    first = evaluate_bond_risk(
        risk_input(strong_redemption=utc_evidence), BondRiskPolicy()
    )
    second = evaluate_bond_risk(
        risk_input(strong_redemption=china_evidence), BondRiskPolicy()
    )
    assert first.input_fingerprint == second.input_fingerprint


@pytest.mark.parametrize(
    "change",
    [
        {"conversion_premium": Decimal("0.151")},
        {
            "strong_redemption": clause().model_copy(
                update={"observed_at": NOW + timedelta(microseconds=1)}
            )
        },
        {
            "strong_redemption": clause().model_copy(
                update={"source": "exchange-announcement "}
            )
        },
    ],
)
def test_fingerprint_changes_for_real_value_time_or_exact_evidence_change(
    change: dict[str, object],
) -> None:
    baseline = evaluate_bond_risk(risk_input(), BondRiskPolicy())
    changed = evaluate_bond_risk(risk_input(**change), BondRiskPolicy())

    assert baseline.input_fingerprint != changed.input_fingerprint


def test_candidate_rejects_risk_for_another_bond() -> None:
    other = evaluate_bond_risk(risk_input(bond_code="113002"), BondRiskPolicy())

    with pytest.raises(ValidationError, match="bond_code"):
        candidate("113001", risk=other)


def test_candidate_rejects_risk_from_changed_premium_snapshot() -> None:
    old = evaluate_bond_risk(risk_input(conversion_premium=Decimal("0.15")), BondRiskPolicy())

    with pytest.raises(ValidationError, match="fingerprint"):
        candidate("113001", conversion_premium=Decimal("0.16"), risk=old)


def test_candidate_rejects_stale_eligible_risk_after_metric_changes() -> None:
    old = evaluate_bond_risk(risk_input(), BondRiskPolicy())

    with pytest.raises(ValidationError, match="fingerprint"):
        candidate("113001", remaining_days=1, risk=old)


def test_candidate_cannot_be_eligible_with_missing_conversion_premium() -> None:
    evidence = clause()
    risk = evaluate_bond_risk(
        risk_input(conversion_premium=None, strong_redemption=evidence), BondRiskPolicy()
    )

    item = candidate(
        "113001", conversion_premium=None, strong_redemption=evidence, risk=risk
    )
    assert item.risk.outcome == "observe_only"


def test_candidate_filter_and_ranking_use_only_bond_metrics_and_risk() -> None:
    first = candidate("113001", conversion_premium=Decimal("0.10"))
    second = candidate("118040", conversion_premium=Decimal("0.20"))
    excluded = candidate(
        "113002",
        remaining_days=1,
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
