from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from qibao_api.contracts.trading import Fill, OrderRequest


def test_order_requires_a_share_symbol_and_board_lot() -> None:
    with pytest.raises(ValidationError):
        OrderRequest(
            client_order_id="order-1",
            symbol="12345",
            side="buy",
            shares=100,
        )

    with pytest.raises(ValidationError):
        OrderRequest(
            client_order_id="order-2",
            symbol="600000",
            side="buy",
            shares=150,
        )


def test_order_rejects_unsupported_side_and_oversize_quantity() -> None:
    with pytest.raises(ValidationError):
        OrderRequest(
            client_order_id="order-3",
            symbol="600000",
            side="short",
            shares=100,
        )

    with pytest.raises(ValidationError):
        OrderRequest(
            client_order_id="order-4",
            symbol="600000",
            side="buy",
            shares=1_000_100,
        )


def test_fill_rejects_non_positive_price() -> None:
    with pytest.raises(ValidationError):
        Fill(
            fill_id="fill-1",
            order_id="order-1",
            symbol="600000",
            side="buy",
            shares=100,
            price=Decimal("-1"),
            gross_amount=Decimal("1000"),
            commission=Decimal("5"),
            slippage=Decimal("1"),
            quote_source="tencent",
            quote_observed_at=datetime(2026, 7, 13, 10, 30),
            risk_decision_id="risk-1",
            filled_at=datetime(2026, 7, 13, 10, 30, 1),
        )
