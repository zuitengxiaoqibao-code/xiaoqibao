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
    decision = repository.get_risk_decision_for_order(result.order_id)
    assert decision.outcome == "reject"
    assert decision.reason_code == "source_unavailable"
    assert decision.rule_version == "availability.1"
    assert "exception_type:RuntimeError" in decision.evidence
    assert "exception_message:quote source offline" in decision.evidence


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
    assert decision.outcome == "reject"
    assert decision.reason_code == "legacy_risk_gate_blocked"
    assert "invalid_reason:规则否决" in decision.evidence
    assert decision.rule_version == "market-quality.1+missing-inputs.1"


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
    decision = repository.get_risk_decision_for_order(result.order_id)
    assert decision.outcome == "reject"
    assert decision.reason_code == "risk_unavailable"


class ApprovingRiskGate:
    def review(self, card):
        return card.model_copy(update={"action": "observe", "invalid_reasons": []})


class IncompleteMarketPipeline(ReviewedPipeline):
    risk_gate = ApprovingRiskGate()


@pytest.mark.asyncio
async def test_missing_industry_and_liquidity_data_is_observe_only(tmp_path) -> None:
    repository = PaperRepository(tmp_path / "paper.sqlite3")
    repository.create_account("paper-1", Decimal("100000"))
    service = PaperTradingService(IncompleteMarketPipeline(), PaperBroker(repository))  # type: ignore[arg-type]

    result = await service.submit("paper-1", OrderRequest(
        client_order_id="missing-risk-data", symbol="600000", side="buy", shares=100,
    ))

    decision = repository.get_risk_decision_for_order(result.order_id)
    assert result.status == "rejected"
    assert decision.outcome == "observe_only"
    assert decision.reason_code == "industry_liquidity_data_missing"
    evidence = "\n".join(decision.evidence)
    assert '"source":"tencent"' in evidence
    assert '"price":"10"' in evidence
    assert '"cash":"100000"' in evidence
    assert '"client_order_id":"missing-risk-data"' in evidence
    assert '"shares":100' in evidence
    assert '"side":"buy"' in evidence
    assert '"single_position_cap":"0.20"' in evidence
    assert '"total_exposure_cap":"0.80"' in evidence
    assert "risk_parameters:quote_age=180s;industry=required;liquidity=required" in evidence


def test_risk_decision_round_trip_preserves_saved_rule_version(tmp_path) -> None:
    from datetime import timezone
    from qibao_api.contracts.risk import RiskDecision

    repository = PaperRepository(tmp_path / "paper.sqlite3")
    repository.create_account("paper-1", Decimal("100000"))
    order_id = repository.create_order(
        "paper-1",
        OrderRequest(client_order_id="versioned", symbol="600000", side="buy", shares=100),
    )
    saved = RiskDecision(
        decision_id="risk-versioned",
        order_id=order_id,
        symbol="600000",
        asset=AssetKind.A_SHARE,
        outcome="observe_only",
        reason_code="industry_data_missing",
        evidence=("order:versioned",),
        rule_id="industry_concentration",
        rule_version="2026-07-13.1",
        decided_at=datetime(2026, 7, 13, 10, 31, tzinfo=timezone.utc),
    )

    repository.record_risk_decision(saved)

    assert repository.get_risk_decision_for_order(order_id) == saved
