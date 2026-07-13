from datetime import timedelta
from uuid import uuid4

from qibao_api.bingbu.paper_broker import PaperBroker, PaperOrderResult
from qibao_api.contracts.trading import OrderRequest
from qibao_api.gongbu.quality import assess_observed_at
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.zhongshu.daily_research import build_market_snapshot


class PaperTradingService:
    def __init__(self, pipeline: ResearchPipeline, broker: PaperBroker) -> None:
        self.pipeline = pipeline
        self.broker = broker

    async def submit(self, account_id: str, request: OrderRequest) -> PaperOrderResult:
        order_id = self.broker.repository.create_order(account_id, request)
        try:
            quote = await self.pipeline.quote_source.fetch(request.symbol)
        except Exception:
            return self.broker.reject_without_quote(
                account_id=account_id,
                request=request,
                reason="source_unavailable",
            )
        assessed = quote.model_copy(
            update={
                "quality": assess_observed_at(
                    quote.observed_at,
                    self.pipeline.clock(),
                    timedelta(minutes=3),
                )
            }
        )
        self.pipeline.repository.save(assessed)
        try:
            reviewed = self.pipeline.risk_gate.review(build_market_snapshot(assessed))
        except Exception:
            return self.broker.reject_without_quote(
                account_id=account_id,
                request=request,
                reason="risk_unavailable",
            )
        risk_approved = reviewed.action != "blocked"
        risk_decision_id = f"risk-{uuid4().hex}"
        risk_decision_id = self.broker.repository.record_risk_decision(
            decision_id=risk_decision_id,
            order_id=order_id,
            approved=risk_approved,
            reasons=reviewed.invalid_reasons,
        )
        return self.broker.submit(
            account_id=account_id,
            request=request,
            quote=assessed,
            risk_decision_id=risk_decision_id,
            risk_approved=risk_approved,
        )
