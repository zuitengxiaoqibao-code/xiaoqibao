from collections.abc import Callable
from datetime import date, datetime, time, timezone
import hashlib
import json
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from qibao_api.a_shares.assessment import DeterministicStockAssessor, StockAssessment
from qibao_api.a_shares.assessment_ai import AIStatus, AssessmentAIExplanation
from qibao_api.a_shares.diagnosis import DiagnosisUnavailableError
from qibao_api.a_shares.instrument_directory import AShareInstrument
from qibao_api.a_shares.preparation import StockPreparation
from qibao_api.contracts.decision import AdviceCard, DecisionPhase, EvidenceReference
from qibao_api.contracts.instruments import AShareCode
from qibao_api.contracts.market import AssetKind
from qibao_api.libu_compliance.repository import SourceAuthorizationError
from qibao_api.shangshu.phase_lifecycle import PhaseExecution, resolve_phase_execution


SECTION_NAMES = (
    "market", "price_volume", "trend", "valuation", "fundamentals",
    "funds", "news", "industry", "risk",
)
PHASES: tuple[DecisionPhase, ...] = ("premarket", "intraday", "postclose")


class UnknownAShareError(LookupError):
    pass


class CockpitSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "partial", "stale", "unavailable", "blocked"]
    source: str
    observed_at: AwareDatetime | None
    snapshot_id: str | None
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class DecisionVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    sequence: int
    generated_at: AwareDatetime
    status: Literal["ready", "partial", "blocked"]


class StockPhaseHistory(BaseModel):
    model_config = ConfigDict(frozen=True)

    advice: tuple[AdviceCard, ...] = ()
    change_stream: tuple[DecisionVersion, ...] = ()
    execution: PhaseExecution | None = None


class StockCockpitSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: AShareCode
    as_of: date
    cutoff: AwareDatetime
    overall_quality: Literal["ready", "partial", "blocked"]
    instrument: AShareInstrument
    preparation: StockPreparation
    candidate_membership: tuple[Literal["short_term", "swing"], ...]
    assessment: StockAssessment
    ai_status: AIStatus
    ai_explanation: AssessmentAIExplanation | None
    current_advice: tuple[AdviceCard, ...]
    sections: dict[str, CockpitSection]
    phases: dict[DecisionPhase, StockPhaseHistory]

    def all_evidence(self) -> tuple[EvidenceReference, ...]:
        return tuple(
            evidence
            for history in self.phases.values()
            for advice in history.advice
            for evidence in (*advice.supporting_evidence, *advice.contrary_evidence)
        )


def _aware(value: datetime | date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return datetime.combine(value, time.min, tzinfo=ZoneInfo("Asia/Shanghai"))


def _unavailable(source: str, reason: str, explanation: str | None = None) -> CockpitSection:
    return CockpitSection(
        status="unavailable", source=source, observed_at=None,
        snapshot_id=None, reason=reason,
        payload={"explanation": explanation} if explanation else {},
    )


def _section_snapshot_id(
    name: str,
    section: Any,
    observed_at: datetime | None,
) -> str:
    content = {
        "name": name,
        "source": section.source,
        "status": section.status,
        "observed_at": observed_at.isoformat() if observed_at is not None else None,
        "metrics": section.metrics,
        "evidence_ids": section.evidence_ids,
        "explanation": section.explanation,
    }
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"diagnosis-section-{hashlib.sha256(encoded).hexdigest()[:24]}"


class StockDecisionCockpitService:
    def __init__(
        self,
        instrument_directory,
        diagnosis_service,
        decision_repository,
        preparation_service,
        assessor=None,
        assessor_ai=None,
        clock: Callable[[], datetime] | None = None,
        trading_calendar=None,
        operations_repository=None,
    ) -> None:
        self.instrument_directory = instrument_directory
        self.diagnosis_service = diagnosis_service
        self.decision_repository = decision_repository
        self.assessor = assessor or DeterministicStockAssessor()
        self.assessor_ai = assessor_ai
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.preparation_service = preparation_service
        self.trading_calendar = trading_calendar
        self.operations_repository = operations_repository

    async def get(
        self, symbol: AShareCode, as_of: date, cutoff: datetime
    ) -> StockCockpitSnapshot:
        instrument = self.instrument_directory.resolve_at(symbol, cutoff)
        if instrument is None:
            raise UnknownAShareError(symbol)

        live_request = as_of == cutoff.astimezone(ZoneInfo("Asia/Shanghai")).date()
        preparation = await self.preparation_service.inspect(
            symbol, as_of=as_of, cutoff=None if live_request else cutoff
        )
        sections = await self._diagnosis_sections(
            symbol, as_of, None if live_request else cutoff
        )
        effective_cutoff = self.clock() if live_request else cutoff
        sections = self._enforce_cutoff(sections, effective_cutoff)
        phases = self._phases(symbol, as_of, effective_cutoff)
        current = self._current_advice(phases)
        membership = self._candidate_membership(current)
        assessment = self.assessor.assess(symbol, sections, membership, effective_cutoff)
        ai_status: AIStatus = "unconfigured"
        ai_explanation = None
        if self.assessor_ai is not None:
            frozen_evidence = (
                *assessment.supporting_evidence, *assessment.contrary_evidence
            )
            ai_result = await self.assessor_ai.explain(assessment, frozen_evidence)
            ai_status = ai_result.status
            ai_explanation = ai_result.explanation
        qualities = {section.status for section in sections.values()}
        overall: Literal["ready", "partial", "blocked"] = (
            "blocked" if "blocked" in qualities else
            "partial" if qualities - {"ready"} else "ready"
        )
        return StockCockpitSnapshot(
            symbol=symbol, as_of=as_of, cutoff=effective_cutoff, overall_quality=overall,
            instrument=instrument, preparation=preparation, candidate_membership=membership,
            assessment=assessment, ai_status=ai_status, ai_explanation=ai_explanation,
            current_advice=current, sections=sections, phases=phases,
        )

    @staticmethod
    def _enforce_cutoff(sections, cutoff):
        return {
            name: (
                _unavailable(section.source, "observed_after_cutoff")
                if section.observed_at is not None and section.observed_at > cutoff
                else section
            )
            for name, section in sections.items()
        }

    async def _diagnosis_sections(self, symbol, as_of, cutoff):
        try:
            diagnosis = (
                await self.diagnosis_service.diagnose(
                    symbol, as_of, persist=False, cutoff=cutoff
                )
                if cutoff is not None
                else await self.diagnosis_service.diagnose(
                    symbol, as_of, persist=False
                )
            )
        except SourceAuthorizationError as exc:
            return {
                name: _unavailable("diagnosis", "source_authorization_required", str(exc))
                for name in SECTION_NAMES
            }
        except DiagnosisUnavailableError as exc:
            return {
                name: _unavailable("diagnosis", "diagnosis_unavailable", str(exc))
                for name in SECTION_NAMES
            }

        mapped = {}
        for target in SECTION_NAMES:
            source_name = "events" if target == "news" else target
            item = diagnosis.sections[source_name]
            observed_at = _aware(item.observed_at)
            if cutoff is not None and observed_at is not None and observed_at > cutoff:
                mapped[target] = _unavailable(item.source, "observed_after_cutoff")
                continue
            mapped[target] = CockpitSection(
                status=item.status, source=item.source, observed_at=observed_at,
                snapshot_id=_section_snapshot_id(target, item, observed_at),
                reason="diagnosis_section_unavailable" if item.status == "unavailable" else None,
                payload={
                    "metrics": item.metrics,
                    "evidence_ids": item.evidence_ids,
                    "explanation": item.explanation,
                },
            )
        return mapped

    @staticmethod
    def _candidate_membership(current_advice):
        horizons = {item.horizon for item in current_advice}
        return tuple(
            candidate for candidate, advice_horizon in (
                ("short_term", "intraday"), ("swing", "swing")
            )
            if advice_horizon in horizons
        )

    def _phases(self, symbol, as_of, cutoff):
        result = {}
        jobs = (
            self.operations_repository.jobs()
            if self.operations_repository is not None else []
        )
        confirmed_trading_day = (
            self.trading_calendar is None
            or self.trading_calendar.is_trading_day(as_of)
        )
        for phase in PHASES:
            advice = []
            versions = []
            included_aggregates = []
            for aggregate in self.decision_repository.cycles(as_of, phase):
                snapshot = aggregate.snapshot
                if snapshot.generated_at > cutoff or any(
                    observed_at > cutoff for observed_at in snapshot.source_observed_at
                ):
                    continue
                selected = tuple(
                    item for item in aggregate.advice
                    if item.asset == AssetKind.A_SHARE and item.symbol == symbol
                    and item.created_at <= cutoff
                    and all(
                        evidence.observed_at <= cutoff
                        for evidence in (*item.supporting_evidence, *item.contrary_evidence)
                    )
                )
                advice.extend(selected)
                included_aggregates.append(aggregate)
                versions.append(DecisionVersion(
                    snapshot_id=snapshot.snapshot_id, sequence=snapshot.sequence,
                    generated_at=snapshot.generated_at, status=snapshot.status,
                ))
            execution = None
            if confirmed_trading_day:
                execution = resolve_phase_execution(
                    phase=phase, trading_date=as_of, now=cutoff,
                    aggregate=(included_aggregates[-1] if included_aggregates else None),
                    jobs=jobs,
                )
            result[phase] = StockPhaseHistory(
                advice=tuple(advice), change_stream=tuple(versions),
                execution=execution,
            )
        return result

    @staticmethod
    def _current_advice(phases):
        latest = {}
        for history in phases.values():
            for item in history.advice:
                key = item.horizon
                if key not in latest or item.created_at > latest[key].created_at:
                    latest[key] = item
        return tuple(
            latest[key] for key in sorted(latest)
            if latest[key].action != "invalidated"
        )
