from decimal import Decimal
from datetime import datetime

import pytest

from qibao_api.bingbu.paper_broker import PaperBroker
from qibao_api.bingbu.paper_service import PaperTradingService
from qibao_api.contracts.trading import OrderRequest
from qibao_api.contracts.market import AssetKind, DataQuality, Quote
from qibao_api.hubu.repository import PaperRepository


class UnavailableQuoteSource:
    async def fetch(self, symbol: str):
        raise RuntimeError("quote source offline")


class FakePipeline:
    quote_source = UnavailableQuoteSource()


@pytest.mark.asyncio
async def test_source_unavailable_order_is_persisted_as_rejected(tmp_path) -> None:
    repository = PaperRepository(tmp_path / "paper.sqlite3")
    repository.create_account("paper-1", Decimal("100000"))
    service = PaperTradingService(FakePipeline(), PaperBroker(repository))  # type: ignore[arg-type]
    request = OrderRequest(
        client_order_id="source-down",
        symbol="600000",
        side="buy",
        shares=100,
    )

    result = await service.submit("paper-1", request)

    assert result.status == "rejected"
    assert result.reason == "source_unavailable"
    assert repository.get_order(result.order_id)["rejection_reason"] == "source_unavailable"


class FreshQuoteSource:
    async def fetch(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol,
            asset=AssetKind.A_SHARE,
            name="浦发银行",
            price=Decimal("10"),
            previous_close=Decimal("10"),
            observed_at=datetime(2026, 7, 13, 10, 30),
            source="tencent",
            quality=DataQuality.FRESH,
        )


class QuoteStore:
    def save(self, quote: Quote) -> None:
        pass


class RejectingRiskGate:
    def review(self, card):
        return card.model_copy(update={"action": "blocked", "invalid_reasons": ["规则否决"]})


class ReviewedPipeline:
    quote_source = FreshQuoteSource()
    repository = QuoteStore()
    risk_gate = RejectingRiskGate()
    clock = staticmethod(lambda: datetime(2026, 7, 13, 10, 31))


@pytest.mark.asyncio
async def test_risk_gate_decision_is_persisted_and_referenced(tmp_path) -> None:
    repository = PaperRepository(tmp_path / "paper.sqlite3")
    repository.create_account("paper-1", Decimal("100000"))
    service = PaperTradingService(ReviewedPipeline(), PaperBroker(repository))  # type: ignore[arg-type]

    result = await service.submit(
        "paper-1",
        OrderRequest(
            client_order_id="risk-denied",
            symbol="600000",
            side="buy",
            shares=100,
        ),
    )

    assert result.status == "rejected"
    assert result.reason == "risk_rejected"
    decision = repository.get_risk_decision_for_order(result.order_id)
    assert decision["approved"] == 0
    assert decision["reasons"] == '["规则否决"]'


class BrokenRiskGate:
    def review(self, card):
        raise RuntimeError("risk engine offline")


class BrokenRiskPipeline(ReviewedPipeline):
    risk_gate = BrokenRiskGate()


@pytest.mark.asyncio
async def test_risk_engine_failure_is_persisted_as_rejected(tmp_path) -> None:
    repository = PaperRepository(tmp_path / "paper.sqlite3")
    repository.create_account("paper-1", Decimal("100000"))
    service = PaperTradingService(BrokenRiskPipeline(), PaperBroker(repository))  # type: ignore[arg-type]

    result = await service.submit(
        "paper-1",
        OrderRequest(
            client_order_id="risk-offline",
            symbol="600000",
            side="buy",
            shares=100,
        ),
    )

    assert result.status == "rejected"
    assert result.reason == "risk_unavailable"
    assert repository.get_order(result.order_id)["rejection_reason"] == "risk_unavailable"
