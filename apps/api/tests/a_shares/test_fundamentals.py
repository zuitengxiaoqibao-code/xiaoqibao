from datetime import datetime, timezone
from decimal import Decimal

from qibao_api.a_shares.fundamentals import TdxFinanceSource, parse_tdx_finance


class FinanceClient:
    def finance(self, symbol):
        return {"jinglirun": "1", "zongguben": "1", "updated_date": 20260331}

    def close(self):
        pass


def test_tdx_finance_source_default_clock_is_utc_aware() -> None:
    snapshot = TdxFinanceSource(client_factory=FinanceClient).fetch("600000")

    assert snapshot.observed_at.tzinfo == timezone.utc


def test_tdx_finance_preserves_real_values_and_missing_fields() -> None:
    snapshot = parse_tdx_finance(
        {
            "jinglirun": "3200000000",
            "zhuyingshouru": "88000000000",
            "jingzichan": "28000000000",
            "zongguben": "2400000000",
            "meigujingzichan": "12.40",
            "updated_date": 20260331,
            "industry": "银行",
        },
        symbol="600000",
        observed_at=datetime(2026, 7, 14, 10, 30),
    )

    assert snapshot.eps == Decimal("3200000000") / Decimal("2400000000")
    assert snapshot.roe == Decimal("3200000000") / Decimal("28000000000") * 100
    assert snapshot.net_profit == Decimal("3200000000")
    assert snapshot.revenue == Decimal("88000000000")
    assert snapshot.book_value_per_share == Decimal("12.40")
    assert snapshot.total_shares == Decimal("2400000000")
    assert snapshot.report_period.isoformat() == "2026-03-31"
    assert snapshot.industry == "银行"
    assert snapshot.source == "mootdx-finance"


def test_tdx_finance_treats_nan_and_zero_placeholder_as_missing() -> None:
    snapshot = parse_tdx_finance(
        {
            "jinglirun": float("nan"), "zhuyingshouru": "--",
            "jingzichan": "", "zongguben": None, "updated_date": 0,
        },
        symbol="600000",
        observed_at=datetime(2026, 7, 14, 10, 30),
    )

    assert snapshot.eps is None
    assert snapshot.roe is None
    assert snapshot.net_profit is None
    assert snapshot.revenue is None
    assert snapshot.report_period is None
