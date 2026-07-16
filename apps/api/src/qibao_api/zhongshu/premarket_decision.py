import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from qibao_api.a_shares.models import CandidateBoard, CandidateEntry
from qibao_api.contracts.decision import (
    AdviceCard, DecisionCycleAggregate, DecisionCycleSnapshot, EvidenceReference,
)
from qibao_api.contracts.market import AssetKind
from qibao_api.zhongshu.decision_ai import DecisionAIEvidence, DecisionAIRequest


CHINA_TZ = timezone(timedelta(hours=8))


class CandidateInputSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    board: CandidateBoard
    captured_at: AwareDatetime
    history_available: bool


class ComplianceInputSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    snapshot_id: str
    captured_at: AwareDatetime
    available: bool
    allowed: bool
    version: str
    risks: tuple[str, ...]


class MarketRiskInputSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    snapshot_id: str
    captured_at: AwareDatetime
    available: bool
    market_state: Literal["strong", "range", "weak", "insufficient_data"]
    version: str
    summary: str
    risks: tuple[str, ...]


class PremarketDecisionService:
    def __init__(
        self, *, candidate_service, news_repository, compliance_checker,
        market_risk_summary, ai_gateway, decision_repository, trading_calendar, clock,
    ) -> None:
        self.candidate_service = candidate_service
        self.news_repository = news_repository
        self.compliance_checker = compliance_checker
        self.market_risk_summary = market_risk_summary
        self.ai_gateway = ai_gateway
        self.decision_repository = decision_repository
        self.trading_calendar = trading_calendar
        self.clock = clock

    def run(self, trading_date: date, now: datetime) -> DecisionCycleAggregate:
        if not self.trading_calendar.is_trading_day(trading_date):
            raise ValueError("unconfirmed trading date")
        previous = self.trading_calendar.previous_trading_day(trading_date)
        window_start = datetime.combine(previous, time(15), CHINA_TZ)
        window_end = min(now.astimezone(CHINA_TZ), datetime.combine(trading_date, time(9, 25), CHINA_TZ))
        if now <= window_start:
            raise ValueError("premarket window has not opened")

        candidates = self.candidate_service.candidates(trading_date, cutoff=window_end)
        compliance = self.compliance_checker.check(trading_date, window_end)
        risk = self.market_risk_summary.summarize(trading_date, window_end)
        candidate_symbols = {
            item.symbol for item in (*candidates.board.short_term, *candidates.board.swing)
        }
        events = tuple(
            event for event in self.news_repository.effective_events(cutoff=window_end)
            if event.review_state == "verified"
            and event.occurred_at <= window_end and event.normalized_at <= window_end
            and any(
                asset is AssetKind.A_SHARE and symbol in candidate_symbols
                for asset, symbol in event.affected_instruments
            )
        )
        interpretations = tuple(
            item for item in self.news_repository.interpretations()
            if item.generated_at <= window_end and any(item.event_id == event.event_id for event in events)
        )
        required_ready = (
            candidates.history_available and candidates.board.as_of <= trading_date
            and candidates.captured_at <= window_end and compliance.available
            and compliance.captured_at <= window_end and risk.available and risk.captured_at <= window_end
        )
        canonical = {
            "phase": "premarket", "trading_date": trading_date.isoformat(),
            "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
            "candidate": candidates.model_dump(mode="json"),
            "compliance": compliance.model_dump(mode="json"),
            "risk": risk.model_dump(mode="json"),
            "events": [item.model_dump(mode="json") for item in events],
            "interpretations": [item.model_dump(mode="json") for item in interpretations],
        }
        input_hash = _canonical_hash(canonical)
        latest = self.decision_repository.latest(trading_date, "premarket")
        if latest is not None and latest.snapshot.input_snapshot_hash == input_hash:
            return latest
        sequence = 1 if latest is None else latest.snapshot.sequence + 1
        snapshot_id = f"premarket-{trading_date.isoformat()}-{input_hash[:20]}"
        advice: tuple[AdviceCard, ...] = ()
        ai_result = None
        if required_ready and compliance.allowed:
            deterministic = self._advice(
                snapshot_id, candidates, compliance, risk, events, window_end,
            )
            if deterministic:
                evidence = _unique_evidence(deterministic)
                request = DecisionAIRequest(
                    generated_at=window_end,
                    evidence=tuple(
                        DecisionAIEvidence(evidence_id=item.evidence_id, summary=item.summary)
                        for item in evidence
                    ),
                    deterministic_conclusions=tuple(item.conclusion for item in deterministic),
                )
                ai_result = self.ai_gateway.explain(request)
                if ai_result.generated_at <= window_end and ai_result.status == "ready":
                    advice = tuple(
                        _with_ai_metadata(item, ai_result).model_copy(update={
                            "plain_language_explanation": ai_result.explanation,
                            "ai_interpretation_id": _ai_identity(ai_result),
                        }) for item in deterministic
                    )
                else:
                    advice = tuple(_with_ai_metadata(item, ai_result) for item in deterministic)
        ai_ready = ai_result is not None and ai_result.status == "ready" and ai_result.generated_at <= window_end
        if not required_ready or not compliance.allowed:
            status, quality = "blocked", "blocked"
        elif not advice and candidates.board.universe_status == "empty":
            status, quality = "partial", "partial"
        elif not ai_ready:
            status, quality = "partial", "partial"
        else:
            status, quality = "ready", "ready"
        quality_reasons = []
        if not candidates.history_available:
            quality_reasons.append("candidate_history_unavailable")
        if candidates.board.as_of > trading_date:
            quality_reasons.append("candidate_as_of_after_trading_date")
        if candidates.captured_at > window_end:
            quality_reasons.append("candidate_snapshot_after_window")
        if not compliance.available:
            quality_reasons.append("compliance_unavailable")
        if compliance.captured_at > window_end:
            quality_reasons.append("compliance_snapshot_after_window")
        if compliance.available and not compliance.allowed:
            quality_reasons.append("compliance_not_allowed")
        if not risk.available:
            quality_reasons.append("risk_unavailable")
        if risk.captured_at > window_end:
            quality_reasons.append("risk_snapshot_after_window")
        if required_ready and compliance.allowed and candidates.board.universe_status == "empty":
            quality_reasons.append("candidate_universe_empty")
        if required_ready and compliance.allowed and not ai_ready:
            quality_reasons.append("ai_unavailable")
        observed = tuple(
            value for value in (candidates.captured_at, compliance.captured_at, risk.captured_at)
            if value <= window_end
        ) + tuple(event.normalized_at for event in events) + tuple(
            item.generated_at for item in interpretations
        )
        source_ids = tuple(dict.fromkeys(filter(None, (
            candidates.board.snapshot_id, compliance.snapshot_id, risk.snapshot_id,
            *(event.event_id for event in events), *(item.interpretation_id for item in interpretations),
        ))))
        snapshot = DecisionCycleSnapshot(
            snapshot_id=snapshot_id, trading_date=trading_date, phase="premarket",
            sequence=sequence, generated_at=max(now, window_end), window_start=window_start,
            window_end=window_end, market_state=risk.market_state if risk.captured_at <= window_end else "insufficient_data",
            data_quality=quality, quality_reasons=tuple(quality_reasons),
            source_snapshot_ids=source_ids, source_observed_at=observed,
            candidate_snapshot_id=candidates.board.snapshot_id if candidates.captured_at <= window_end else None,
            news_event_ids=tuple(event.event_id for event in events),
            risk_event_ids=(risk.snapshot_id,) if risk.captured_at <= window_end else (),
            input_snapshot_hash=input_hash,
            previous_snapshot_id=None if latest is None else latest.snapshot.snapshot_id,
            status=status, ai_status="ready" if ai_ready else "unavailable",
        )
        aggregate = DecisionCycleAggregate(snapshot=snapshot, advice=advice)
        self.decision_repository.append_cycle(aggregate)
        persisted = self.decision_repository.latest(trading_date, "premarket")
        if persisted is None:
            raise RuntimeError("decision repository did not persist the aggregate")
        return persisted

    @staticmethod
    def _advice(snapshot_id, candidates, compliance, risk, events, created_at):
        results = []
        for horizon, entries in (
            ("intraday", candidates.board.short_term), ("swing", candidates.board.swing),
        ):
            for item in entries:
                related = tuple(
                    event for event in events
                    if (AssetKind.A_SHARE, item.symbol) in event.affected_instruments
                )
                adverse = tuple(event for event in related if _is_risk_event(event))
                action = "wait" if adverse else "observe"
                supporting = (_factor_evidence(candidates, item),)
                contrary = tuple(_news_evidence(event) for event in adverse)
                results.append(AdviceCard(
                    advice_id=f"advice-{snapshot_id}-{horizon}-{item.symbol}", snapshot_id=snapshot_id,
                    asset=AssetKind.A_SHARE, symbol=item.symbol, horizon=horizon,
                    observation_state="watching" if action == "observe" else "waiting",
                    action=action, conclusion="保留观察" if action == "observe" else "等待核验正向证据",
                    confidence=Decimal("0.6") if action == "observe" else Decimal("0.3"),
                    supporting_evidence=supporting, contrary_evidence=contrary,
                    risks=tuple(dict.fromkeys((*risk.risks, *compliance.risks))) or ("数据可能变化",),
                    invalidation_conditions=("候选因子或核验新闻发生变化",),
                    quantitative_result={"candidate_score": item.score},
                    strategy_version=f"{item.factor_snapshot.factor_version}/{risk.version}/{compliance.version}",
                    created_at=created_at,
                ))
        return tuple(results)


def _factor_evidence(snapshot: CandidateInputSnapshot, item: CandidateEntry) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"factor-{snapshot.board.snapshot_id}-{item.horizon}-{item.symbol}",
        source=item.factor_snapshot.source, snapshot_id=snapshot.board.snapshot_id or "candidate-board",
        summary=f"候选因子快照 {item.factor_snapshot.factor_version}", observed_at=snapshot.captured_at,
    )


def _news_evidence(event) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"news-{event.event_id}", source=event.citations[0].publisher,
        snapshot_id=event.event_id, summary=event.headline, observed_at=event.normalized_at,
    )


def _is_risk_event(event) -> bool:
    return "risk" in event.event_type or "风险事件" in event.themes


def _unique_evidence(advice):
    values = {}
    for item in advice:
        for evidence in (*item.supporting_evidence, *item.contrary_evidence):
            values.setdefault(evidence.evidence_id, evidence)
    return tuple(values.values())


def _canonical_hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ai_identity(result) -> str:
    return f"decision-ai-{_canonical_hash(result.model_dump(mode='json'))[:24]}"


def _with_ai_metadata(advice: AdviceCard, result) -> AdviceCard:
    metadata = {
        "ai_provider": result.provider,
        "ai_model": result.model,
        "ai_prompt_version": result.prompt_version,
        "ai_generated_at": result.generated_at.isoformat(),
        "ai_evidence_ids": ",".join(result.evidence_ids),
        "ai_invalid_output_count": str(result.invalid_output_count),
        "ai_provider_error_count": str(result.provider_error_count),
    }
    return advice.model_copy(update={"quantitative_result": {**advice.quantitative_result, **metadata}})
