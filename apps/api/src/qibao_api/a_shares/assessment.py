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
    generated_at: AwareDatetime


def _digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evidence(name: str, section: Any, cutoff: datetime) -> EvidenceReference:
    metrics = section.payload.get("metrics", {})
    observed_at = section.observed_at or cutoff
    content = {
        "section": name,
        "source": section.source,
        "observed_at": observed_at.isoformat(),
        "status": section.status,
        "reason": section.reason,
        "metrics": metrics,
    }
    evidence_id = _digest(content)
    snapshot_id = section.snapshot_id or f"assessment-source-{evidence_id[:16]}"
    summary = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    return EvidenceReference(
        evidence_id=evidence_id,
        source=section.source,
        snapshot_id=snapshot_id,
        summary=summary,
        observed_at=observed_at,
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
        else:
            action = "observe"
            conclusion = "行情与日线数据可用且无风险阻断，保持观察。"
            confidence = Decimal("0.75")

        supporting = tuple(
            _evidence(name, section, cutoff)
            for name, section in sorted(usable.items())
            if section.status == "ready"
        )
        contrary = tuple(
            _evidence(name, section, cutoff)
            for name, section in sorted(usable.items())
            if section.status in {"unavailable", "blocked"}
        )
        assessment_id = _digest({
            "symbol": symbol,
            "cutoff": cutoff.isoformat(),
            "action": action,
            "candidate_membership": candidate_membership,
            "supporting_evidence": [item.evidence_id for item in supporting],
            "contrary_evidence": [item.evidence_id for item in contrary],
        })
        simulation_eligible = bool(candidate_membership) and action == "observe"
        risks = (
            "风险分区阻断。" if action == "avoid" else
            "核心行情或趋势证据不足。" if action == "wait" else
            "市场与基本面条件可能在截止时间后变化。"
        )
        return StockAssessment(
            assessment_id=assessment_id,
            symbol=symbol,
            action=action,
            conclusion=conclusion,
            confidence=confidence,
            supporting_evidence=supporting,
            contrary_evidence=contrary,
            risks=(risks,),
            invalidation_conditions=("任一核心分区状态或指标发生变化。",),
            simulation_eligible=simulation_eligible,
            generated_at=cutoff,
        )
