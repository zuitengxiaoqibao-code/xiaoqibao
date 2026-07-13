from datetime import datetime, timedelta, timezone
from hashlib import sha256

from qibao_api.bingbu.paper_broker import PaperBroker, PaperOrderResult
from qibao_api.contracts.trading import OrderRequest
from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import RiskDecision
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
            self._record_system_decision(order_id, request, "source_unavailable")
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
            self._record_system_decision(order_id, request, "risk_unavailable")
            return self.broker.reject_without_quote(
                account_id=account_id,
                request=request,
                reason="risk_unavailable",
            )
        risk_approved = False
        now = self._aware(self.pipeline.clock())
        blocked = reviewed.action == "blocked"
        reason = "legacy_risk_gate_blocked" if blocked else "industry_liquidity_data_missing"
        decision = self._decision(
            order_id, request, "reject" if blocked else "observe_only", reason,
            "pipeline:risk-gate", "complete_order_review", "2026-07-13.1", now,
        )
        risk_decision_id = self.broker.repository.record_risk_decision(decision)
        return self.broker.submit(
            account_id=account_id,
            request=request,
            quote=assessed,
            risk_decision_id=risk_decision_id,
            risk_approved=risk_approved,
        )

    def _record_system_decision(self, order_id: str, request: OrderRequest, reason: str) -> None:
        self.broker.repository.record_risk_decision(
            self._decision(order_id, request, "reject", reason, f"order:{order_id}", "system_availability", "system.1", datetime.now(timezone.utc))
        )

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @staticmethod
    def _decision(order_id, request, outcome, reason, evidence, rule_id, version, decided_at):
        identity = f"{order_id}:{rule_id}:{version}"
        return RiskDecision(
            decision_id=f"risk_{sha256(identity.encode('utf-8')).hexdigest()}", order_id=order_id,
            symbol=request.symbol, asset=AssetKind.A_SHARE, outcome=outcome,
            reason_code=reason, evidence=(evidence,), rule_id=rule_id,
            rule_version=version, decided_at=decided_at,
        )
