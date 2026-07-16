from datetime import date

from qibao_api.convertible_bonds.backtest_policy import (
    BondBacktestExecutionPolicy,
    BondStrategyExecutionRequest,
)


def test_default_policy_forbids_same_day_sale() -> None:
    policy = BondBacktestExecutionPolicy.for_request(BondStrategyExecutionRequest())

    assert policy.settlement == "T+1"
    assert policy.can_sell(acquired_on=date(2026, 7, 14), sell_on=date(2026, 7, 14)) is False
    assert policy.can_sell(acquired_on=date(2026, 7, 14), sell_on=date(2026, 7, 15)) is True


def test_same_day_sale_requires_explicit_strategy_request() -> None:
    policy = BondBacktestExecutionPolicy.for_request(
        BondStrategyExecutionRequest(enable_t0=True)
    )

    assert policy.settlement == "T+0"
    assert policy.can_sell(acquired_on=date(2026, 7, 14), sell_on=date(2026, 7, 14)) is True


def test_policy_rejects_sale_before_acquisition_even_with_t0() -> None:
    policy = BondBacktestExecutionPolicy.for_request(
        BondStrategyExecutionRequest(enable_t0=True)
    )

    assert policy.can_sell(acquired_on=date(2026, 7, 14), sell_on=date(2026, 7, 13)) is False
