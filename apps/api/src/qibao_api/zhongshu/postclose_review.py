import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints

from qibao_api.contracts.decision import (
    AdviceCard,
    DecisionCycleAggregate,
    DecisionCycleSnapshot,
)
from qibao_api.contracts.market import AssetKind


CHINA_TZ = timezone(timedelta(hours=8))
POSTCLOSE_STRATEGY_VERSION = "postclose-review-v2"
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OutcomeStatus = Literal["correct", "wrong", "invalidated", "risk_blocked", "unverifiable"]
ErrorAttribution = Literal[
    "data_issue",
    "news_misread",
    "trend_failure",
    "risk_event",
    "rule_block",
    "data_unavailable",
]


class AdviceOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    advice_id: NonBlank
    original_snapshot_id: NonBlank
    status: OutcomeStatus
    attribution: ErrorAttribution
    outcome_input_hash: str
    reviewed_at: AwareDatetime
    withdrawal_reason: str | None = None


class PostcloseReviewResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    aggregate: DecisionCycleAggregate
    outcomes: tuple[AdviceOutcome, ...]
    next_day_observations: tuple[NonBlank, ...]


class PostcloseReviewService:
    def __init__(
        self,
        *,
        decision_repository,
        market_outcome_source,
        audit_repository,
        ai_gateway=None,
    ) -> None:
        self.decision_repository = decision_repository
        self.market_outcome_source = market_outcome_source
        self.audit_repository = audit_repository
        self.ai_gateway = ai_gateway

    def run(self, trading_date: date, now: datetime) -> PostcloseReviewResult:
        close = datetime.combine(trading_date, time(15), CHINA_TZ)
        if now.astimezone(CHINA_TZ) < close:
            raise ValueError("postclose review cannot run before market close")
        open_at = datetime.combine(trading_date, time(9, 25), CHINA_TZ)
        advice = self._frozen_advice(trading_date, close)
        advice_ids = tuple(item.advice_id for item in advice)
        market = self.market_outcome_source.list_market_outcomes(advice_ids, open_at, close)
        findings = self.audit_repository.list_findings(asset=AssetKind.A_SHARE)
        inputs_by_id = {
            item.advice_id: self._canonical_inputs(
                item, market, findings, open_at, close,
            )
            for item in advice
        }
        outcomes = tuple(
            self._outcome(item, inputs_by_id[item.advice_id], now)
            for item in advice
        )
        outcomes = tuple(sorted(outcomes, key=lambda item: item.advice_id))
        next_day = tuple(
            item.advice_id for item in outcomes
            if item.status == "correct"
            or (item.status == "unverifiable" and item.withdrawal_reason is None)
        )
        input_hash = _canonical_hash({
            "trading_date": trading_date,
            "strategy_version": POSTCLOSE_STRATEGY_VERSION,
            "advice": advice,
            "outcomes": tuple(
                item.model_dump(mode="json", exclude={"reviewed_at"}) for item in outcomes
            ),
            "next_day_observations": next_day,
        })
        latest = self.decision_repository.latest(trading_date, "postclose")
        if latest is not None and latest.snapshot.input_snapshot_hash == input_hash:
            return PostcloseReviewResult(
                aggregate=latest, outcomes=outcomes, next_day_observations=next_day,
            )
        sequence = 1 if latest is None else latest.snapshot.sequence + 1
        snapshot_id = f"postclose-{trading_date.isoformat()}-{sequence}-{input_hash[:16]}"
        outcomes_by_id = {item.advice_id: item for item in outcomes}
        derived = tuple(
            self._postclose_advice(item, outcomes_by_id[item.advice_id], snapshot_id)
            for item in advice
        )
        canonical_inputs = tuple(
            item
            for advice_id in sorted(inputs_by_id)
            for collection in inputs_by_id[advice_id].values()
            for item in collection
        )
        observed_at = tuple(sorted({
            value for value in (_observed_at(item) for item in canonical_inputs)
            if value is not None
        }))
        aggregate = DecisionCycleAggregate(
            snapshot=DecisionCycleSnapshot(
                snapshot_id=snapshot_id,
                trading_date=trading_date,
                phase="postclose",
                sequence=sequence,
                generated_at=now,
                window_start=open_at,
                window_end=close,
                market_state="insufficient_data" if any(
                    item.status == "unverifiable" for item in outcomes
                ) else "range",
                data_quality="partial" if any(
                    item.status == "unverifiable" for item in outcomes
                ) else "ready",
                source_snapshot_ids=tuple(item.outcome_input_hash for item in outcomes),
                source_observed_at=observed_at,
                candidate_snapshot_id=None,
                news_event_ids=(),
                risk_event_ids=tuple(sorted(
                    str(_value(item, "finding_id")) for item in canonical_inputs
                    if _value(item, "finding_id")
                )),
                input_snapshot_hash=input_hash,
                previous_snapshot_id=None if latest is None else latest.snapshot.snapshot_id,
                status="partial" if any(
                    item.status == "unverifiable" for item in outcomes
                ) else "ready",
                ai_status="not_requested",
            ),
            advice=derived,
        )
        self.decision_repository.append_cycle(aggregate)
        persisted = self.decision_repository.latest(trading_date, "postclose")
        if persisted is None:
            raise RuntimeError("decision repository did not persist the postclose aggregate")
        return PostcloseReviewResult(
            aggregate=persisted, outcomes=outcomes, next_day_observations=next_day,
        )

    def _frozen_advice(self, trading_date: date, close: datetime) -> tuple[AdviceCard, ...]:
        values: dict[str, AdviceCard] = {}
        for phase in ("premarket", "intraday"):
            for cycle in self.decision_repository.cycles(trading_date, phase):
                if cycle.snapshot.generated_at > close or cycle.snapshot.window_end > close:
                    continue
                for item in cycle.advice:
                    if item.created_at > close:
                        continue
                    previous = values.get(item.advice_id)
                    if previous is not None and previous != item:
                        raise ValueError(f"conflicting duplicate advice_id: {item.advice_id}")
                    values[item.advice_id] = item
        return tuple(values[key] for key in sorted(values))

    @staticmethod
    def _canonical_inputs(
        advice, market, findings, window_start, close,
    ):
        def attributed(item, *, finding=False):
            linked = advice.advice_id in tuple(_value(item, "input_snapshot_ids", ())) if finding else (
                _value(item, "advice_id") == advice.advice_id
            )
            observed = _observed_at(item)
            return (
                linked
                and observed is not None
                and observed > advice.created_at
                and window_start <= observed <= close
            )

        return {
            "market": tuple(sorted(
                (item for item in market if attributed(item)), key=_evidence_sort_key,
            )),
            "findings": tuple(sorted(
                (item for item in findings if attributed(item, finding=True)),
                key=_evidence_sort_key,
            )),
        }

    @staticmethod
    def _outcome(advice, inputs, now):
        market_values = inputs["market"]
        finding_values = inputs["findings"]
        canonical = {
            "advice_id": advice.advice_id,
            "original_snapshot_id": advice.snapshot_id,
            "market": market_values,
            "findings": finding_values,
        }
        invalidated = next(
            (item for item in market_values if _value(item, "invalidation_triggered", False)),
            None,
        )
        available = [item for item in market_values if _value(item, "available", False)]
        blocked = next((item for item in finding_values if _value(item, "severity") == "critical"), None)
        if blocked is not None:
            status, attribution, reason = "risk_blocked", "rule_block", "risk finding blocked advice"
        elif invalidated is not None:
            status, attribution, reason = "invalidated", "risk_event", "invalidation condition triggered"
        elif not available:
            status, attribution, reason = "unverifiable", "data_unavailable", None
        elif _value(available[-1], "direction") == "favorable":
            status, attribution, reason = "correct", "trend_failure", None
        else:
            attribution = "data_issue" if _value(available[-1], "data_issue", False) else (
                "news_misread" if _value(available[-1], "news_misread", False) else "trend_failure"
            )
            status, reason = "wrong", "outcome contradicted advice"
        return AdviceOutcome(
            advice_id=advice.advice_id,
            original_snapshot_id=advice.snapshot_id,
            status=status,
            attribution=attribution,
            outcome_input_hash=_canonical_hash(canonical),
            reviewed_at=now,
            withdrawal_reason=reason,
        )

    @staticmethod
    def _postclose_advice(
        original: AdviceCard, outcome: AdviceOutcome, snapshot_id: str,
    ) -> AdviceCard:
        retained = outcome.status in {"correct", "unverifiable"} and outcome.withdrawal_reason is None
        labels = {
            "correct": "判断成立",
            "unverifiable": "无法验证",
            "wrong": "判断未成立",
            "invalidated": "条件失效",
            "risk_blocked": "风险拦截",
        }
        outcome_label = labels[outcome.status]
        conclusion = (
            "复盘验证通过，列入次日观察"
            if outcome.status == "correct"
            else "收盘数据不足，保留观察但需补齐验证"
            if outcome.status == "unverifiable" and retained
            else "复盘未验证通过，撤回原结论"
        )
        explanation = (
            f"盘前/盘中结论为“{original.conclusion}”。"
            f"收盘后结果：{outcome_label}。"
            + (
                "次日继续观察，但仍需重新核验行情和风险。"
                if retained else "原判断不再沿用，下一交易日重新评估。"
            )
        )
        quantitative = {
            **original.quantitative_result,
            "outcome_status": outcome.status,
            "outcome_label": outcome_label,
            "error_attribution": outcome.attribution,
            "outcome_input_hash": outcome.outcome_input_hash,
            "original_advice_id": original.advice_id,
            "original_snapshot_id": original.snapshot_id,
        }
        return original.model_copy(update={
            "advice_id": f"postclose-{outcome.outcome_input_hash[:24]}",
            "snapshot_id": snapshot_id,
            "action": "observe" if retained else "invalidated",
            "observation_state": "next_day_observation" if retained else "withdrawn_revalidation_required",
            "conclusion": conclusion,
            "plain_language_explanation": explanation,
            "quantitative_result": quantitative,
            "risk_decision_id": None,
            "previous_advice_id": original.advice_id,
            "changed_fields": (
                "action", "conclusion", "plain_language_explanation",
                "quantitative_result", "strategy_version",
                "outcome_status", "observation_state",
            ),
            "strategy_version": f"{POSTCLOSE_STRATEGY_VERSION}/{original.strategy_version}",
            "created_at": outcome.reviewed_at,
        })


def _value(value: Any, field: str, default=None):
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _observed_at(value: Any):
    for field in ("observed_at", "detected_at", "created_at"):
        found = _value(value, field)
        if found is not None:
            return found
    return None


def _within(value: Any, start: datetime, end: datetime) -> bool:
    observed = _observed_at(value)
    return observed is not None and start <= observed <= end


def _evidence_sort_key(value: Any) -> tuple[datetime, str, str]:
    observed = _observed_at(value)
    if observed is None:
        raise ValueError("canonical evidence requires an observed timestamp")
    identity = next((
        str(_value(value, field))
        for field in (
            "outcome_id", "finding_id", "snapshot_id", "source_snapshot_id",
        )
        if _value(value, field)
    ), "")
    return observed, identity, _canonical_hash(value)


def _canonical_hash(value: Any) -> str:
    def default(item):
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        raise TypeError(f"cannot hash {type(item)!r}")

    payload = json.dumps(
        value, default=default, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
