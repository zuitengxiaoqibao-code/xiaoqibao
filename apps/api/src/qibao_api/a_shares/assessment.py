import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from qibao_api.contracts.decision import EvidenceReference
from qibao_api.contracts.instruments import AShareCode


class StockAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    assessment_id: str
    symbol: AShareCode
    action: Literal["observe", "wait", "avoid"]
    conclusion: str
    confidence: Decimal = Field(ge=0, le=1)
    supporting_evidence: tuple[EvidenceReference, ...]
    contrary_evidence: tuple[EvidenceReference, ...]
    risks: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    simulation_eligible: bool
    authorized_simulation_advice_id: str | None
    authorized_simulation_plan_id: str | None
    generated_at: AwareDatetime


def _digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evidence(name: str, section: Any) -> EvidenceReference | None:
    if section.observed_at is None or section.snapshot_id is None:
        return None
    metrics = section.payload.get("metrics", {})
    content = {
        "section": name,
        "source": section.source,
        "observed_at": section.observed_at.isoformat(),
        "status": section.status,
        "reason": section.reason,
        "metrics": metrics,
    }
    evidence_id = _digest(content)
    summary = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    return EvidenceReference(
        evidence_id=evidence_id,
        source=section.source,
        snapshot_id=section.snapshot_id,
        summary=summary,
        observed_at=section.observed_at,
    )


class DeterministicStockAssessor:
    def assess(
        self,
        symbol: AShareCode,
        sections: dict[str, Any],
        candidate_membership: tuple[Literal["short_term", "swing"], ...],
        cutoff: datetime,
    ) -> StockAssessment:
        usable = {
            name: section
            for name, section in sections.items()
            if section.observed_at is None or section.observed_at <= cutoff
        }
        risk = usable.get("risk")
        market = usable.get("market")
        trend = usable.get("trend")

        risk_metrics = risk.payload.get("metrics", {}) if risk is not None else {}
        trend_metrics = trend.payload.get("metrics", {}) if trend is not None else {}
        adverse_count = sum(
            int(section.payload.get("metrics", {}).get("adverse_event_count", 0) or 0)
            for name, section in usable.items() if name in {"news", "industry"}
        )
        missing_count = int(risk_metrics.get("missing_section_count", 0) or 0)
        volatility = Decimal(str(trend_metrics.get("volatility_20d", 0) or 0))
        drawdown = Decimal(str(trend_metrics.get("drawdown_60d", 0) or 0))
        material_risk = (
            missing_count >= 3 or adverse_count > 0
            or volatility >= Decimal("0.08") or drawdown <= Decimal("-0.20")
        )

        if risk is not None and risk.status == "blocked":
            action: Literal["observe", "wait", "avoid"] = "avoid"
            conclusion = "权威风险分区已阻断，当前应回避。"
            confidence = Decimal("0.90")
        elif market is None or market.status != "ready":
            action = "wait"
            conclusion = "实时行情不可验证，等待行情恢复后再研判。"
            confidence = Decimal("0.40")
        elif trend is None or trend.status != "ready":
            action = "wait"
            conclusion = "日线趋势样本不足，等待有效日线数据。"
            confidence = Decimal("0.40")
        elif material_risk:
            action = "avoid"
            conclusion = "重大风险指标或反方证据成立，当前应回避。"
            confidence = Decimal("0.85")
        else:
            action = "observe"
            conclusion = "行情与日线数据可用且无风险阻断，保持观察。"
            confidence = Decimal("0.75")

        supporting = tuple(
            evidence
            for name, section in sorted(usable.items())
            if section.status == "ready"
            if (evidence := _evidence(name, section)) is not None
        )
        contrary = tuple(
            evidence
            for name, section in sorted(usable.items())
            if section.status in {"partial", "unavailable", "blocked"}
            if (evidence := _evidence(name, section)) is not None
        )
        assessment_id = _digest({
            "symbol": symbol,
            "cutoff": cutoff.isoformat(),
            "action": action,
            "candidate_membership": candidate_membership,
            "supporting_evidence": [item.evidence_id for item in supporting],
            "contrary_evidence": [item.evidence_id for item in contrary],
        })
        missing = tuple(
            name for name, section in sorted(sections.items())
            if section.observed_at is None or section.observed_at > cutoff
        )
        snapshot_risks = tuple(
            f"source_snapshot_unavailable:{name}"
            for name, section in sorted(usable.items())
            if section.observed_at is not None and section.snapshot_id is None
        )
        primary_risk = (
            "风险分区阻断。" if action == "avoid" else
            "核心行情或趋势证据不足。" if action == "wait" else
            "市场与基本面条件可能在截止时间后变化。"
        )
        metric_risks = tuple(
            reason for condition, reason in (
                (missing_count >= 3, f"关键分区缺失数量较高：{missing_count}。"),
                (adverse_count > 0, f"存在重大反方事件：{adverse_count}。"),
                (volatility >= Decimal("0.08"), f"20日波动率偏高：{volatility}。"),
                (drawdown <= Decimal("-0.20"), f"60日回撤较深：{drawdown}。"),
            ) if condition
        )
        risks = (primary_risk, *metric_risks, *(
            (f"缺失或晚于截止时间的分区：{'、'.join(missing)}。",) if missing else ()
        ), *snapshot_risks)
        return StockAssessment(
            assessment_id=assessment_id,
            symbol=symbol,
            action=action,
            conclusion=conclusion,
            confidence=confidence,
            supporting_evidence=supporting,
            contrary_evidence=contrary,
            risks=risks,
            invalidation_conditions=(
                "任一核心分区状态或指标发生变化。", *snapshot_risks
            ),
            simulation_eligible=False,
            authorized_simulation_advice_id=None,
            authorized_simulation_plan_id=None,
            generated_at=cutoff,
        )
