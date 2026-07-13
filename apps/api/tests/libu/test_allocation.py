from decimal import Decimal

from qibao_api.contracts.trading import OrderRequest, PaperAccount, Position
from qibao_api.libu.allocation import AllocationPolicy


def account(cash: str = "100000", equity: str = "100000", exposure: str = "0") -> PaperAccount:
    return PaperAccount(
        account_id="paper-1",
        initial_cash=Decimal("100000"),
        cash=Decimal(cash),
        total_equity=Decimal(equity),
        exposure=Decimal(exposure),
    )


def buy(shares: int) -> OrderRequest:
    return OrderRequest(
        client_order_id=f"buy-{shares}",
        symbol="600000",
        side="buy",
        shares=shares,
    )


def test_rejects_order_when_estimated_cost_exceeds_cash() -> None:
    decision = AllocationPolicy().review(
        account=account(cash="1000"),
        positions=[],
        order=buy(200),
        estimated_price=Decimal("10"),
        estimated_fees=Decimal("5"),
    )

    assert decision.approved is False
    assert decision.reason == "insufficient_cash"


def test_rejects_order_above_single_position_cap() -> None:
    decision = AllocationPolicy().review(
        account=account(),
        positions=[],
        order=buy(2100),
        estimated_price=Decimal("10"),
        estimated_fees=Decimal("5"),
    )

    assert decision.approved is False
    assert decision.reason == "single_position_cap"


def test_rejects_order_above_total_exposure_cap() -> None:
    decision = AllocationPolicy().review(
        account=account(cash="25000", exposure="0.75"),
        positions=[
            Position(
                symbol="000001",
                shares=7500,
                average_cost=Decimal("10"),
                market_value=Decimal("75000"),
            )
        ],
        order=buy(600),
        estimated_price=Decimal("10"),
        estimated_fees=Decimal("5"),
    )

    assert decision.approved is False
    assert decision.reason == "total_exposure_cap"


def test_approves_order_within_all_limits() -> None:
    decision = AllocationPolicy().review(
        account=account(),
        positions=[],
        order=buy(1000),
        estimated_price=Decimal("10"),
        estimated_fees=Decimal("5"),
    )

    assert decision.approved is True
    assert decision.reason is None
