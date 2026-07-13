from datetime import datetime
from decimal import Decimal

import pytest

from qibao_api.bingbu.paper_broker import PaperBroker
from qibao_api.contracts.market import AssetKind, DataQuality, Quote
from qibao_api.contracts.trading import OrderRequest
from qibao_api.hubu.repository import PaperRepository


@pytest.fixture
def repository(tmp_path) -> PaperRepository:
    value = PaperRepository(tmp_path / "paper.sqlite3")
    value.create_account("paper-1", Decimal("100000"))
    return value


def quote(*, price: str = "10", quality: DataQuality = DataQuality.FRESH) -> Quote:
    return Quote(
        symbol="600000",
        asset=AssetKind.A_SHARE,
        name="浦发银行",
        price=Decimal(price),
        previous_close=Decimal("10"),
        observed_at=datetime(2026, 7, 13, 10, 30),
        source="tencent",
        quality=quality,
    )


def order(client_order_id: str = "client-1") -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        symbol="600000",
        side="buy",
        shares=100,
    )


def test_filled_order_keeps_quote_and_risk_evidence(repository) -> None:
    result = PaperBroker(repository).submit(
        account_id="paper-1",
        request=order(),
        quote=quote(),
        risk_decision_id="risk-1",
        risk_approved=True,
    )

    assert result.status == "filled"
    assert result.fill is not None
    assert result.fill.quote_source == "tencent"
    assert result.fill.quote_observed_at == datetime(2026, 7, 13, 10, 30)
    assert result.fill.risk_decision_id == "risk-1"
    assert repository.get_order(result.order_id)["status"] == "filled"


@pytest.mark.parametrize(
    ("market_quote", "risk_approved", "reason"),
    [
        (quote(quality=DataQuality.STALE), True, "quote_not_fresh"),
        (quote(), False, "risk_rejected"),
        (quote(price="11"), True, "limit_up_buy"),
    ],
)
def test_rejected_order_is_persisted_with_reason(
    repository, market_quote, risk_approved, reason
) -> None:
    result = PaperBroker(repository).submit(
        account_id="paper-1",
        request=order(reason),
        quote=market_quote,
        risk_decision_id="risk-1",
        risk_approved=risk_approved,
    )

    assert result.status == "rejected"
    assert result.reason == reason
    saved = repository.get_order(result.order_id)
    assert saved["status"] == "rejected"
    assert saved["rejection_reason"] == reason


def test_insufficient_funds_is_persisted(repository) -> None:
    result = PaperBroker(repository).submit(
        account_id="paper-1",
        request=OrderRequest(
            client_order_id="too-large",
            symbol="600000",
            side="buy",
            shares=10000,
        ),
        quote=quote(),
        risk_decision_id="risk-1",
        risk_approved=True,
    )

    assert result.status == "rejected"
    assert result.reason == "insufficient_cash"


def test_limit_down_sell_is_persisted_before_position_check(repository) -> None:
    result = PaperBroker(repository).submit(
        account_id="paper-1",
        request=OrderRequest(
            client_order_id="limit-down-sell",
            symbol="600000",
            side="sell",
            shares=100,
        ),
        quote=quote(price="9"),
        risk_decision_id="risk-1",
        risk_approved=True,
    )

    assert result.status == "rejected"
    assert result.reason == "limit_down_sell"
