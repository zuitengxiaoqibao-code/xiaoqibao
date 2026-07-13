from decimal import Decimal

from pydantic import BaseModel

from qibao_api.contracts.trading import OrderRequest, PaperAccount, Position


class AllocationDecision(BaseModel):
    approved: bool
    reason: str | None = None
    estimated_cash_required: Decimal
    projected_single_position: Decimal
    projected_exposure: Decimal


class AllocationPolicy:
    def __init__(
        self,
        *,
        single_position_cap: Decimal = Decimal("0.20"),
        total_exposure_cap: Decimal = Decimal("0.80"),
    ) -> None:
        self.single_position_cap = single_position_cap
        self.total_exposure_cap = total_exposure_cap

    def review(
        self,
        *,
        account: PaperAccount,
        positions: list[Position],
        order: OrderRequest,
        estimated_price: Decimal,
        estimated_fees: Decimal,
    ) -> AllocationDecision:
        gross = estimated_price * order.shares
        current_market_value = sum(
            (position.market_value for position in positions), Decimal("0")
        )
        current_symbol_value = sum(
            (
                position.market_value
                for position in positions
                if position.symbol == order.symbol
            ),
            Decimal("0"),
        )
        current_symbol_shares = sum(
            position.shares for position in positions if position.symbol == order.symbol
        )
        direction = Decimal("1") if order.side == "buy" else Decimal("-1")
        projected_symbol_value = max(Decimal("0"), current_symbol_value + direction * gross)
        projected_market_value = max(Decimal("0"), current_market_value + direction * gross)
        projected_single = projected_symbol_value / account.total_equity
        projected_exposure = projected_market_value / account.total_equity
        cash_required = gross + estimated_fees if order.side == "buy" else Decimal("0")

        reason = None
        if order.side == "sell" and order.shares > current_symbol_shares:
            reason = "insufficient_shares"
        elif cash_required > account.cash:
            reason = "insufficient_cash"
        elif projected_single > self.single_position_cap:
            reason = "single_position_cap"
        elif projected_exposure > self.total_exposure_cap:
            reason = "total_exposure_cap"

        return AllocationDecision(
            approved=reason is None,
            reason=reason,
            estimated_cash_required=cash_required,
            projected_single_position=projected_single,
            projected_exposure=projected_exposure,
        )
