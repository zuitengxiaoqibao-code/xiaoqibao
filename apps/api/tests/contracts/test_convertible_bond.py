from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from qibao_api.contracts.convertible_bond import ClauseDates, ConvertibleBondContract
from qibao_api.contracts.market import AssetKind


def valid_contract(**overrides: object) -> ConvertibleBondContract:
    values = {
        "bond_code": "113001",
        "linked_stock": "600000",
        "conversion_price": Decimal("9.87"),
        "maturity": date(2030, 7, 14),
        "remaining_size": Decimal("12.345678"),
        "clause_dates": ClauseDates(
            conversion_start=date(2026, 1, 1),
            redemption_start=date(2026, 7, 1),
            put_back_start=date(2029, 1, 1),
        ),
        "as_of": datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return ConvertibleBondContract(**values)


def test_accepts_convertible_bond_with_decimal_inputs_and_fixed_asset() -> None:
    contract = valid_contract()

    assert contract.bond_code == "113001"
    assert contract.asset is AssetKind.CONVERTIBLE_BOND
    assert contract.conversion_price == Decimal("9.87")
    assert contract.remaining_size == Decimal("12.345678")


@pytest.mark.parametrize("linked_stock", ["430001", "830001", "920001"])
def test_accepts_beijing_stock_exchange_linked_stock(linked_stock: str) -> None:
    assert valid_contract(linked_stock=linked_stock).linked_stock == linked_stock


@pytest.mark.parametrize("bond_code", ["11300", "11300A", "600000", "100001"])
def test_rejects_invalid_convertible_bond_codes(bond_code: str) -> None:
    with pytest.raises(ValidationError):
        valid_contract(bond_code=bond_code)


@pytest.mark.parametrize("linked_stock", ["113001", "30000A", "60000", "900001"])
def test_rejects_invalid_linked_a_share_codes(linked_stock: str) -> None:
    with pytest.raises(ValidationError):
        valid_contract(linked_stock=linked_stock)


@pytest.mark.parametrize(
    ("field", "value"),
    [("conversion_price", Decimal("0")), ("conversion_price", Decimal("-1")),
     ("remaining_size", Decimal("-0.01"))],
)
def test_rejects_non_positive_price_and_negative_remaining_size(
    field: str, value: Decimal
) -> None:
    with pytest.raises(ValidationError):
        valid_contract(**{field: value})


def test_requires_timezone_aware_snapshot_time() -> None:
    with pytest.raises(ValidationError):
        valid_contract(as_of=datetime(2026, 7, 14, 9, 30))


def test_rejects_clause_dates_after_maturity() -> None:
    clauses = ClauseDates(conversion_start=date(2030, 7, 15))

    with pytest.raises(ValidationError):
        valid_contract(clause_dates=clauses)


def test_historical_contract_and_clause_dates_are_frozen() -> None:
    contract = valid_contract()

    with pytest.raises(ValidationError):
        contract.conversion_price = Decimal("10")
    with pytest.raises(ValidationError):
        contract.clause_dates.conversion_start = date(2026, 2, 1)
