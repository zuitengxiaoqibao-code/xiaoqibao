from datetime import timedelta
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import RiskDecision


Outcome = Literal["approve", "reduce", "reject", "observe_only"]
RULE_VERSION = "2026-07-13.1"


class RiskContext(BaseModel):
    """Immutable A-share order snapshot and the limits used to review it."""

    model_config = ConfigDict(frozen=True)

    order_id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(pattern=r"^\d{6}$")
    asset: Literal[AssetKind.A_SHARE]
    decided_at: AwareDatetime
    quote_observed_at: AwareDatetime
    max_quote_age: timedelta = Field(ge=timedelta(0))
    projected_position: Decimal = Field(ge=0)
    max_position: Decimal = Field(ge=0)
    projected_total_exposure: Decimal = Field(ge=0)
    max_total_exposure: Decimal = Field(ge=0)
    projected_industry_exposure: Decimal = Field(ge=0)
    max_industry_exposure: Decimal = Field(ge=0)
    order_value: Decimal = Field(ge=0)
    average_daily_turnover: Decimal = Field(gt=0)
    max_turnover_participation: Decimal = Field(ge=0)
    current_drawdown: Decimal = Field(ge=0)
    max_drawdown: Decimal = Field(ge=0)
    snapshot_reference: str = Field(min_length=1)


class Rule(Protocol):
    rule_id: str

    def evaluate(self, context: RiskContext) -> RiskDecision: ...


class BaseRule:
    rule_id: str
    rule_version = RULE_VERSION
    breach_outcome: Outcome
    breach_reason_code: str
    approval_reason_code: str

    def breached(self, context: RiskContext) -> bool:
        raise NotImplementedError

    def evaluate(self, context: RiskContext) -> RiskDecision:
        is_breached = self.breached(context)
        outcome: Outcome = self.breach_outcome if is_breached else "approve"
        reason_code = self.breach_reason_code if is_breached else self.approval_reason_code
        return RiskDecision(
            decision_id=f"{context.order_id}:{self.rule_id}:{self.rule_version}",
            order_id=context.order_id,
            symbol=context.symbol,
            asset=context.asset,
            outcome=outcome,
            reason_code=reason_code,
            evidence=(context.snapshot_reference,),
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            decided_at=context.decided_at,
        )


class DataFreshnessRule(BaseRule):
    rule_id = "data_freshness"
    breach_outcome: Outcome = "reject"
    breach_reason_code = "quote_data_stale"
    approval_reason_code = "quote_data_fresh"

    def breached(self, context: RiskContext) -> bool:
        return context.decided_at - context.quote_observed_at > context.max_quote_age


class MaxPositionRule(BaseRule):
    rule_id = "max_position"
    breach_outcome: Outcome = "reduce"
    breach_reason_code = "max_position_exceeded"
    approval_reason_code = "within_max_position"

    def breached(self, context: RiskContext) -> bool:
        return context.projected_position > context.max_position


class TotalExposureRule(BaseRule):
    rule_id = "total_exposure"
    breach_outcome: Outcome = "reduce"
    breach_reason_code = "total_exposure_exceeded"
    approval_reason_code = "within_total_exposure"

    def breached(self, context: RiskContext) -> bool:
        return context.projected_total_exposure > context.max_total_exposure


class IndustryConcentrationRule(BaseRule):
    rule_id = "industry_concentration"
    breach_outcome: Outcome = "reduce"
    breach_reason_code = "industry_concentration_exceeded"
    approval_reason_code = "within_industry_concentration"

    def breached(self, context: RiskContext) -> bool:
        return context.projected_industry_exposure > context.max_industry_exposure


class LiquidityRule(BaseRule):
    rule_id = "liquidity"
    breach_outcome: Outcome = "observe_only"
    breach_reason_code = "liquidity_limit_exceeded"
    approval_reason_code = "within_liquidity_limit"

    def breached(self, context: RiskContext) -> bool:
        allowed_value = context.average_daily_turnover * context.max_turnover_participation
        return context.order_value > allowed_value


class AccountDrawdownRule(BaseRule):
    rule_id = "account_drawdown"
    breach_outcome: Outcome = "reject"
    breach_reason_code = "account_drawdown_exceeded"
    approval_reason_code = "within_account_drawdown"

    def breached(self, context: RiskContext) -> bool:
        return context.current_drawdown > context.max_drawdown


class RiskEngine:
    _OUTCOME_PRIORITY = {
        "approve": 0,
        "reduce": 1,
        "observe_only": 2,
        "reject": 3,
    }

    def __init__(self, rules: tuple[Rule, ...]) -> None:
        if not rules:
            raise ValueError("at least one risk rule is required")
        self.rules = rules

    def evaluate_all(self, context: RiskContext) -> tuple[RiskDecision, ...]:
        return tuple(rule.evaluate(context) for rule in self.rules)

    def review(self, context: RiskContext) -> RiskDecision:
        decisions = self.evaluate_all(context)
        return min(
            decisions,
            key=lambda decision: (
                -self._OUTCOME_PRIORITY[decision.outcome],
                decision.rule_id,
                decision.rule_version,
            ),
        )
