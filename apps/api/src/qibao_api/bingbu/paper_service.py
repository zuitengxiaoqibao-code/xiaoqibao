from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from decimal import Decimal

from qibao_api.bingbu.paper_broker import PaperBroker, PaperOrderResult
from qibao_api.contracts.trading import OrderRequest
from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import RiskDecision
from qibao_api.gongbu.quality import assess_observed_at
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.zhongshu.daily_research import build_market_snapshot
from qibao_api.xingbu.rules import (
    RULE_VERSION, AccountDrawdownRule, DataFreshnessRule, IndustryConcentrationRule,
    LiquidityRule, MaxPositionRule, RiskContext, RiskEngine, TotalExposureRule,
)


class PaperTradingService:
    def __init__(self, pipeline: ResearchPipeline, broker: PaperBroker) -> None:
        self.pipeline = pipeline
        self.broker = broker

    async def submit(self, account_id: str, request: OrderRequest) -> PaperOrderResult:
        existing = self.broker.repository.get_order_by_client_id(account_id, request.client_order_id)
        if existing is not None and existing["status"] != "pending":
            if existing["status"] == "filled":
                return PaperOrderResult(order_id=str(existing["order_id"]), status="filled", fill=self.broker.repository.get_fill_for_order(str(existing["order_id"])))
            return PaperOrderResult(order_id=str(existing["order_id"]), status="rejected", reason=str(existing["rejection_reason"]))
        order_id = self.broker.repository.create_order(account_id, request)
        try:
            quote = await self.pipeline.quote_source.fetch(request.symbol)
        except Exception as error:
            return self._fail(order_id, account_id, request, "source_unavailable", error)
        try:
            assessed = quote.model_copy(update={"quality": assess_observed_at(quote.observed_at, self.pipeline.clock(), timedelta(minutes=3))})
            self.pipeline.repository.save(assessed)
            reviewed = self.pipeline.risk_gate.review(build_market_snapshot(assessed))
            account = self.broker.repository.get_account(account_id)
            positions = self.broker.repository.list_positions(account_id)
            single_cap, total_cap = self.broker.repository.get_allocation_settings(account_id)
            position_value = next((item.market_value for item in positions if item.symbol == request.symbol), Decimal("0"))
            order_value = assessed.price * request.shares
            signed_value = order_value if request.side == "buy" else -order_value
            equity = account.total_equity or Decimal("1")
            context = RiskContext(
                order_id=order_id, symbol=request.symbol, asset=AssetKind.A_SHARE,
                decided_at=self._aware(self.pipeline.clock()), quote_observed_at=self._aware(assessed.observed_at),
                max_quote_age=timedelta(minutes=3),
                projected_position=max(Decimal("0"), position_value + signed_value) / equity,
                max_position=single_cap,
                projected_total_exposure=max(Decimal("0"), account.exposure * equity + signed_value) / equity,
                max_total_exposure=total_cap,
                projected_industry_exposure=None, max_industry_exposure=Decimal("0.30"),
                order_value=order_value, average_daily_turnover=None,
                max_turnover_participation=Decimal("0.01"),
                current_drawdown=max(Decimal("0"), (account.initial_cash - account.total_equity) / account.initial_cash),
                max_drawdown=Decimal("0.10"), snapshot_reference=f"risk-context:{order_id}",
            )
            engine = RiskEngine((DataFreshnessRule(), MaxPositionRule(), TotalExposureRule(), IndustryConcentrationRule(), LiquidityRule(), AccountDrawdownRule()))
            trace = engine.evaluate_all(context)
            winner = engine.review(context)
        except Exception as error:
            return self._fail(order_id, account_id, request, "risk_unavailable", error)
        quote_snapshot = json.dumps({
            "source": assessed.source, "observed_at": assessed.observed_at.isoformat(),
            "quality": assessed.quality.value, "price": str(assessed.price),
        }, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        account_snapshot = json.dumps({
            "cash": str(account.cash), "equity": str(account.total_equity),
            "exposure": str(account.exposure),
            "positions": [position.model_dump(mode="json") for position in positions],
            "single_position_cap": str(single_cap), "total_exposure_cap": str(total_cap),
        }, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        order_snapshot = json.dumps({
            "client_order_id": request.client_order_id, "symbol": request.symbol,
            "side": request.side, "shares": request.shares,
        }, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        evidence = (
            f"order_snapshot:{order_snapshot}", f"quote_snapshot:{quote_snapshot}",
            f"account_snapshot:{account_snapshot}",
            "risk_parameters:quote_age=180s;industry=required;liquidity=required",
            f"execution_parameters:commission_rate={self.broker.commission_rate};minimum_commission={self.broker.minimum_commission};slippage_rate={self.broker.slippage_rate}",
            *(f"invalid_reason:{item}" for item in reviewed.invalid_reasons),
            f"risk_context:{context.model_dump_json()}",
            f"rule_trace:{json.dumps([item.model_dump(mode='json') for item in trace], ensure_ascii=True, sort_keys=True, separators=(',', ':'))}",
        )
        decision = winner.model_copy(update={"evidence": evidence, "rule_version": RULE_VERSION})
        try:
            try:
                stored_decision = self.broker.repository.get_risk_decision_for_order(order_id)
            except KeyError:
                stored_decision = decision
                self.broker.repository.record_risk_decision(stored_decision)
            risk_decision_id = stored_decision.decision_id
            return self.broker.submit(account_id=account_id, request=request, quote=assessed, risk_decision_id=risk_decision_id, risk_approved=stored_decision.outcome == "approve")
        except Exception as error:
            return self._fail(order_id, account_id, request, "order_processing_failed", error, persist=False)

    def _record_system_decision(self, order_id: str, request: OrderRequest, reason: str, error: Exception) -> None:
        order_snapshot = json.dumps({
            "client_order_id": request.client_order_id, "symbol": request.symbol,
            "side": request.side, "shares": request.shares,
        }, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        self.broker.repository.record_risk_decision(
            self._decision(order_id, request, "reject", reason, (
                f"order:{order_id}", f"order_snapshot:{order_snapshot}",
                f"exception_type:{type(error).__name__}",
                f"exception_message:{str(error) or 'unavailable'}",
            ), "system_availability", "availability.1", datetime.now(timezone.utc))
        )

    def _fail(self, order_id: str, account_id: str, request: OrderRequest, reason: str, error: Exception, *, persist: bool = True) -> PaperOrderResult:
        if persist:
            try:
                self._record_system_decision(order_id, request, reason, error)
            except Exception:
                pass
        try:
            saved = self.broker.repository.get_order(order_id)
            if saved["status"] == "pending":
                self.broker.repository.reject_order(order_id, reason)
        except Exception:
            pass
        return PaperOrderResult(order_id=order_id, status="rejected", reason=reason)

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
