from datetime import date, datetime, time, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from qibao_api.a_shares.diagnosis import DiagnosisUnavailableError
from qibao_api.a_shares.instrument_directory import AShareInstrument
from qibao_api.contracts.decision import AdviceCard, DecisionPhase, EvidenceReference
from qibao_api.contracts.instruments import AShareCode
from qibao_api.contracts.market import AssetKind
from qibao_api.libu_compliance.repository import SourceAuthorizationError


SECTION_NAMES = (
    "market", "price_volume", "trend", "valuation", "fundamentals",
    "funds", "news", "industry", "risk", "backtest",
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


class StockCockpitSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: AShareCode
    as_of: date
    cutoff: AwareDatetime
    overall_quality: Literal["ready", "partial", "blocked"]
    instrument: AShareInstrument
    candidate_membership: tuple[Literal["short_term", "swing"], ...]
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
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _unavailable(source: str, reason: str) -> CockpitSection:
    return CockpitSection(
        status="unavailable", source=source, observed_at=None,
        snapshot_id=None, reason=reason, payload={},
    )


class StockDecisionCockpitService:
    def __init__(self, instrument_directory, diagnosis_service, decision_repository) -> None:
        self.instrument_directory = instrument_directory
        self.diagnosis_service = diagnosis_service
        self.decision_repository = decision_repository

    async def get(
        self, symbol: AShareCode, as_of: date, cutoff: datetime
    ) -> StockCockpitSnapshot:
        instrument = self.instrument_directory.resolve(symbol)
        if instrument is None:
            raise UnknownAShareError(symbol)

        sections = await self._diagnosis_sections(symbol, as_of, cutoff)
        sections["funds"] = _unavailable("not-connected", "fund_data_not_connected")
        sections["backtest"] = _unavailable("not-run", "backtest_not_run")
        phases = self._phases(symbol, as_of, cutoff)
        current = self._current_advice(phases)
        membership = self._candidate_membership(current)
        qualities = {section.status for section in sections.values()}
        overall: Literal["ready", "partial", "blocked"] = (
            "blocked" if "blocked" in qualities else
            "partial" if qualities - {"ready"} else "ready"
        )
        return StockCockpitSnapshot(
            symbol=symbol, as_of=as_of, cutoff=cutoff, overall_quality=overall,
            instrument=instrument, candidate_membership=membership,
            current_advice=current, sections=sections, phases=phases,
        )

    async def _diagnosis_sections(self, symbol, as_of, cutoff):
        try:
            diagnosis = await self.diagnosis_service.diagnose(
                symbol, as_of, persist=False
            )
        except SourceAuthorizationError:
            return {
                name: _unavailable("diagnosis", "source_authorization_required")
                for name in SECTION_NAMES if name not in {"funds", "backtest"}
            }
        except DiagnosisUnavailableError:
            return {
                name: _unavailable("diagnosis", "diagnosis_unavailable")
                for name in SECTION_NAMES if name not in {"funds", "backtest"}
            }

        mapped = {}
        for target in SECTION_NAMES:
            if target in {"funds", "backtest"}:
                continue
            source_name = "events" if target == "news" else target
            item = diagnosis.sections[source_name]
            observed_at = _aware(item.observed_at)
            if observed_at is not None and observed_at > cutoff:
                mapped[target] = _unavailable(item.source, "observed_after_cutoff")
                continue
            mapped[target] = CockpitSection(
                status=item.status, source=item.source, observed_at=observed_at,
                snapshot_id=diagnosis.snapshot_id,
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
        for phase in PHASES:
            advice = []
            versions = []
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
                if not selected:
                    continue
                advice.extend(selected)
                versions.append(DecisionVersion(
                    snapshot_id=snapshot.snapshot_id, sequence=snapshot.sequence,
                    generated_at=snapshot.generated_at, status=snapshot.status,
                ))
            result[phase] = StockPhaseHistory(
                advice=tuple(advice), change_stream=tuple(versions)
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
