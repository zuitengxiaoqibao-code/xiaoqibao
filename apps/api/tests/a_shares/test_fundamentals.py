from datetime import datetime
from decimal import Decimal

from qibao_api.a_shares.fundamentals import parse_tdx_finance


def test_tdx_finance_preserves_real_values_and_missing_fields() -> None:
    snapshot = parse_tdx_finance(
        {
            "eps": "1.25",
            "roe": "11.8",
            "profit": "3200000000",
            "income": "88000000000",
            "bvps": "12.40",
        },
        symbol="600000",
        observed_at=datetime(2026, 7, 14, 10, 30),
    )

    assert snapshot.eps == Decimal("1.25")
    assert snapshot.roe == Decimal("11.8")
    assert snapshot.net_profit == Decimal("3200000000")
    assert snapshot.revenue == Decimal("88000000000")
    assert snapshot.book_value_per_share == Decimal("12.40")
    assert snapshot.total_shares is None
    assert snapshot.source == "mootdx-finance"


def test_tdx_finance_treats_nan_and_zero_placeholder_as_missing() -> None:
    snapshot = parse_tdx_finance(
        {"eps": float("nan"), "roe": "", "profit": None, "income": "--"},
        symbol="600000",
        observed_at=datetime(2026, 7, 14, 10, 30),
    )

    assert snapshot.eps is None
    assert snapshot.roe is None
    assert snapshot.net_profit is None
    assert snapshot.revenue is None
