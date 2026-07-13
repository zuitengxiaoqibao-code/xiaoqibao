from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from qibao_api.contracts.market import AssetKind, DataQuality, Quote
from qibao_api.contracts.trading import Fill, OrderRequest
from qibao_api.hubu.repository import PaperRepository
from qibao_api.libu.allocation import AllocationPolicy


class PaperOrderResult(BaseModel):
    order_id: str
    status: Literal["filled", "rejected"]
    reason: str | None = None
    fill: Fill | None = None


class PaperBroker:
    def __init__(
        self,
        repository: PaperRepository,
        *,
        commission_rate: Decimal = Decimal("0.0003"),
        minimum_commission: Decimal = Decimal("5"),
        slippage_rate: Decimal = Decimal("0.0005"),
    ) -> None:
        self.repository = repository
        self.commission_rate = commission_rate
        self.minimum_commission = minimum_commission
        self.slippage_rate = slippage_rate

    def submit(
        self,
        *,
        account_id: str,
        request: OrderRequest,
        quote: Quote,
        risk_decision_id: str,
        risk_approved: bool,
    ) -> PaperOrderResult:
        order_id = self.repository.create_order(account_id, request)
        saved = self.repository.get_order(order_id)
        if saved["status"] != "pending":
            return PaperOrderResult(
                order_id=order_id,
                status=saved["status"],
                reason=saved["rejection_reason"],
            )

        rejection = self._preflight_reason(request, quote, risk_approved)
        execution_price = self._execution_price(request, quote.price)
        gross = execution_price * request.shares
        commission = max(gross * self.commission_rate, self.minimum_commission)
        if rejection is None:
            single_cap, total_cap = self.repository.get_allocation_settings(account_id)
            allocation = AllocationPolicy(
                single_position_cap=single_cap,
                total_exposure_cap=total_cap,
            ).review(
                account=self.repository.get_account(account_id),
                positions=self.repository.list_positions(account_id),
                order=request,
                estimated_price=execution_price,
                estimated_fees=commission,
            )
            rejection = allocation.reason
        if rejection is not None:
            self.repository.reject_order(order_id, rejection)
            return PaperOrderResult(order_id=order_id, status="rejected", reason=rejection)

        fill = Fill(
            fill_id=f"fill-{uuid4().hex}",
            order_id=order_id,
            symbol=request.symbol,
            side=request.side,
            shares=request.shares,
            price=execution_price,
            gross_amount=gross,
            commission=commission,
            slippage=abs(execution_price - quote.price) * request.shares,
            quote_source=quote.source,
            quote_observed_at=quote.observed_at,
            risk_decision_id=risk_decision_id,
            filled_at=datetime.now(timezone.utc),
        )
        self.repository.apply_fill(account_id, fill, order_id=order_id)
        return PaperOrderResult(order_id=order_id, status="filled", fill=fill)

    def _preflight_reason(
        self, request: OrderRequest, quote: Quote, risk_approved: bool
    ) -> str | None:
        if (
            quote.asset is not AssetKind.A_SHARE
            or quote.symbol != request.symbol
            or quote.quality is not DataQuality.FRESH
        ):
            return "quote_not_fresh"
        if not risk_approved:
            return "risk_rejected"
        change = quote.price / quote.previous_close
        if request.side == "buy" and change >= Decimal("1.10"):
            return "limit_up_buy"
        if request.side == "sell" and change <= Decimal("0.90"):
            return "limit_down_sell"
        return None

    def _execution_price(self, request: OrderRequest, quote_price: Decimal) -> Decimal:
        direction = Decimal("1") if request.side == "buy" else Decimal("-1")
        return quote_price * (Decimal("1") + direction * self.slippage_rate)
