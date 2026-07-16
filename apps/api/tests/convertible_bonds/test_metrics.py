import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

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


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "convertible_bonds"
    / "eastmoney_118040_20260713.json"
)


def eastmoney_118040() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_eastmoney_118040_conversion_value_matches_published_field() -> None:
    # Endpoint https://datacenter-web.eastmoney.com/api/data/v1/get,
    # report RPTA_WEB_KZZ_LS, retrieved 2026-07-14; data date 2026-07-13,
    # ZCODE 118040, source Eastmoney.
    record = eastmoney_118040()["record"]
    value = conversion_value(
        par_value=Decimal("100"),
        conversion_price=Decimal("28.51"),
        stock_price=Decimal("31.3"),
    )

    published = Decimal(record["SWAPVALUE"])
    assert abs(value - published) <= Decimal("0.000000001")


def test_eastmoney_118040_premiums_match_published_percent_fields() -> None:
    # SWAPOR and PUREBONDOR are published percentages, so divide them by 100
    # before comparing with the ratio returned by this domain module.
    record = eastmoney_118040()["record"]
    conversion = Decimal(record["SWAPVALUE"])
    bond_price = Decimal(record["FCLOSE"])
    pure_bond_value = Decimal(record["PUREBONDVALUE"])

    swap_ratio = conversion_premium(bond_price, conversion)
    pure_ratio = pure_bond_premium(bond_price, pure_bond_value)

    assert swap_ratio is not None
    assert pure_ratio is not None
    assert abs(swap_ratio - Decimal("0.006102415335")) <= Decimal("0.000000000001")
    assert abs(pure_ratio - Decimal("0.095701919302")) <= Decimal("0.000000000001")
    assert abs(swap_ratio - Decimal(record["SWAPOR"]) / Decimal("100")) <= Decimal(
        "0.000000000001"
    )
    assert abs(pure_ratio - Decimal(record["PUREBONDOR"]) / Decimal("100")) <= Decimal(
        "0.00000000001"
    )


def test_simple_hand_calculated_examples_use_fixed_expected_constants() -> None:
    assert conversion_value(Decimal("100"), Decimal("20"), Decimal("30")) == Decimal("150")
    assert conversion_premium(Decimal("165"), Decimal("150")) == Decimal("0.1")
    assert pure_bond_premium(Decimal("110"), Decimal("100")) == Decimal("0.1")


def test_display_boundary_rounds_without_changing_calculation_value() -> None:
    value = conversion_value(Decimal("100"), Decimal("9.87"), Decimal("10.25"))

    assert format_decimal(value, places=2) == "103.85"
    assert value == Decimal("103.8500506585612968591691996")


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
