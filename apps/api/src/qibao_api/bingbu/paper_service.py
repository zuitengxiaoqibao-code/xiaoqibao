from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

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
        except Exception as error:
            self._record_system_decision(order_id, request, "source_unavailable", error)
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
        except Exception as error:
            self._record_system_decision(order_id, request, "risk_unavailable", error)
            return self.broker.reject_without_quote(
                account_id=account_id,
                request=request,
                reason="risk_unavailable",
            )
        risk_approved = False
        now = self._aware(self.pipeline.clock())
        blocked = reviewed.action == "blocked"
        reason = "legacy_risk_gate_blocked" if blocked else "industry_liquidity_data_missing"
        account = self.broker.repository.get_account(account_id)
        positions = self.broker.repository.list_positions(account_id)
        quote_snapshot = json.dumps({
            "source": assessed.source, "observed_at": assessed.observed_at.isoformat(),
            "quality": assessed.quality.value, "price": str(assessed.price),
        }, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        account_snapshot = json.dumps({
            "cash": str(account.cash), "equity": str(account.total_equity),
            "exposure": str(account.exposure),
            "positions": [position.model_dump(mode="json") for position in positions],
        }, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        evidence = (
            f"quote_snapshot:{quote_snapshot}", f"account_snapshot:{account_snapshot}",
            "risk_parameters:quote_age=180s;industry=required;liquidity=required",
            *(f"invalid_reason:{item}" for item in reviewed.invalid_reasons),
        )
        decision = self._decision(
            order_id, request, "reject" if blocked else "observe_only", reason,
            evidence, "complete_order_review", "market-quality.1+missing-inputs.1", now,
        )
        risk_decision_id = self.broker.repository.record_risk_decision(decision)
        return self.broker.submit(
            account_id=account_id,
            request=request,
            quote=assessed,
            risk_decision_id=risk_decision_id,
            risk_approved=risk_approved,
        )

    def _record_system_decision(self, order_id: str, request: OrderRequest, reason: str, error: Exception) -> None:
        self.broker.repository.record_risk_decision(
            self._decision(order_id, request, "reject", reason, (
                f"order:{order_id}", f"exception_type:{type(error).__name__}",
                f"exception_message:{str(error) or 'unavailable'}",
            ), "system_availability", "availability.1", datetime.now(timezone.utc))
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
            reason_code=reason, evidence=(evidence,) if isinstance(evidence, str) else evidence, rule_id=rule_id,
            rule_version=version, decided_at=decided_at,
        )
