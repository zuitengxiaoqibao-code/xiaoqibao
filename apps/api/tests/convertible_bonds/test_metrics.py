from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from qibao_api.convertible_bonds.metrics import (
    EvidenceBackedClauseState,
    calculate_metrics,
    conversion_premium,
    conversion_value,
    format_decimal,
    pure_bond_premium,
    remaining_term,
)


def test_published_conversion_value_formula_keeps_decimal_precision() -> None:
    # Published formula: par / conversion price * linked-stock price.
    value = conversion_value(
        par_value=Decimal("100"),
        conversion_price=Decimal("9.87"),
        stock_price=Decimal("10.25"),
    )

    assert value == Decimal("100") / Decimal("9.87") * Decimal("10.25")
    assert value != value.quantize(Decimal("0.01"))


def test_premium_formulas_match_hand_calculation_without_rounding() -> None:
    conversion = Decimal("100") / Decimal("9.87") * Decimal("10.25")

    assert conversion_premium(Decimal("121.50"), conversion) == (
        Decimal("121.50") - conversion
    ) / conversion
    assert pure_bond_premium(Decimal("121.50"), Decimal("92.40")) == (
        Decimal("121.50") - Decimal("92.40")
    ) / Decimal("92.40")


def test_display_boundary_rounds_without_changing_calculation_value() -> None:
    value = conversion_value(Decimal("100"), Decimal("9.87"), Decimal("10.25"))

    assert format_decimal(value, places=2) == "103.85"
    assert value == Decimal("100") / Decimal("9.87") * Decimal("10.25")


def test_remaining_term_uses_exact_days_and_declares_actual_365() -> None:
    term = remaining_term(as_of=date(2026, 7, 14), maturity=date(2027, 7, 14))

    assert term.days == 365
    assert term.years == Decimal("1")
    assert term.day_count == "actual/365"


def test_remaining_term_counts_leap_day_and_rejects_expired_bond() -> None:
    term = remaining_term(as_of=date(2023, 7, 1), maturity=date(2024, 7, 1))

    assert term.days == 366
    assert term.years == Decimal("366") / Decimal("365")
    with pytest.raises(ValueError, match="before as_of"):
        remaining_term(as_of=date(2026, 7, 15), maturity=date(2026, 7, 14))


@pytest.mark.parametrize(
    ("function", "args"),
    [
        (conversion_value, (Decimal("100"), Decimal("0"), Decimal("10"))),
        (conversion_premium, (Decimal("120"), Decimal("0"))),
        (pure_bond_premium, (Decimal("120"), Decimal("0"))),
    ],
)
def test_zero_denominators_are_rejected(function: object, args: tuple[Decimal, ...]) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        function(*args)  # type: ignore[operator]


def test_missing_or_suspended_prices_do_not_create_inferred_metrics() -> None:
    missing_stock = calculate_metrics(
        par_value=Decimal("100"),
        conversion_price=Decimal("9.87"),
        stock_price=None,
        bond_price=Decimal("121.50"),
        pure_bond_value=None,
        as_of=date(2026, 7, 14),
        maturity=date(2030, 7, 14),
        remaining_size=Decimal("12.345678"),
    )
    suspended = calculate_metrics(
        par_value=Decimal("100"),
        conversion_price=Decimal("9.87"),
        stock_price=Decimal("10.25"),
        bond_price=Decimal("121.50"),
        pure_bond_value=Decimal("92.40"),
        as_of=date(2026, 7, 14),
        maturity=date(2030, 7, 14),
        remaining_size=Decimal("12.345678"),
        bond_suspended=True,
    )

    assert missing_stock.conversion_value is None
    assert missing_stock.conversion_premium is None
    assert missing_stock.pure_bond_premium is None
    assert suspended.conversion_value is not None
    assert suspended.conversion_premium is None
    assert suspended.pure_bond_premium is None


def test_suspended_linked_stock_disables_stock_based_metrics() -> None:
    metrics = calculate_metrics(
        par_value=Decimal("100"),
        conversion_price=Decimal("9.87"),
        stock_price=Decimal("10.25"),
        bond_price=Decimal("121.50"),
        pure_bond_value=Decimal("92.40"),
        as_of=date(2026, 7, 14),
        maturity=date(2030, 7, 14),
        remaining_size=Decimal("12.345678"),
        stock_suspended=True,
    )

    assert metrics.conversion_value is None
    assert metrics.conversion_premium is None
    assert metrics.pure_bond_premium is not None


def test_remaining_size_is_preserved_as_direct_evidence_input() -> None:
    metrics = calculate_metrics(
        par_value=Decimal("100"),
        conversion_price=Decimal("9.87"),
        stock_price=Decimal("10.25"),
        bond_price=Decimal("121.50"),
        pure_bond_value=Decimal("92.40"),
        as_of=date(2026, 7, 14),
        maturity=date(2030, 7, 14),
        remaining_size=Decimal("12.345678901"),
    )

    assert metrics.remaining_size == Decimal("12.345678901")


def test_strong_redemption_state_requires_clause_evidence_and_data_time() -> None:
    observed_at = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)
    evidence = EvidenceBackedClauseState(
        bond_code="113001",
        state="triggered",
        clause_text="issuer announcement states the strong-redemption condition was met",
        source="exchange-announcement",
        observed_at=observed_at,
    )

    assert evidence.state == "triggered"
    assert evidence.observed_at == observed_at

    for missing in ("clause_text", "source", "observed_at"):
        values = {
            "bond_code": "113001",
            "state": "triggered",
            "clause_text": "explicit clause evidence",
            "source": "exchange-announcement",
            "observed_at": observed_at,
        }
        values.pop(missing)
        with pytest.raises(ValidationError):
            EvidenceBackedClauseState(**values)


def test_strong_redemption_evidence_rejects_naive_time_and_non_bond_code() -> None:
    with pytest.raises(ValidationError):
        EvidenceBackedClauseState(
            bond_code="600000",
            state="triggered",
            clause_text="explicit clause evidence",
            source="exchange-announcement",
            observed_at=datetime(2026, 7, 14, 9, 30),
        )
