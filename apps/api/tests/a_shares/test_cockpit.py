from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from qibao_api.a_shares.cockpit import StockDecisionCockpitService
from qibao_api.a_shares.diagnosis import AShareDiagnosis, DiagnosisSection
from qibao_api.a_shares.instrument_directory import AShareInstrument
from qibao_api.contracts.decision import (
    AdviceCard,
    DecisionCycleAggregate,
    DecisionCycleSnapshot,
    EvidenceReference,
)
from qibao_api.contracts.market import AssetKind
from qibao_api.shangshu.decision_repository import DecisionIntegrityError


TRADE_DATE = date(2026, 7, 15)
CUTOFF = datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)


class Directory:
    def resolve(self, symbol):
        if symbol != "600000":
            return None
        return AShareInstrument(
            symbol=symbol, name="浦发银行", exchange="sh",
            observed_at=CUTOFF, quote_quality="ready",
        )


class Diagnosis:
    async def diagnose(self, symbol, as_of):
        sections = {
            name: DiagnosisSection(
                status="ready", observed_at=CUTOFF, source="fixture",
                metrics={"symbol": symbol}, explanation="fixture",
            )
            for name in (
                "market", "price_volume", "trend", "valuation", "fundamentals",
                "events", "industry", "risk",
            )
        }
        return AShareDiagnosis(
            symbol=symbol, as_of=as_of, action="observe", overall_status="ready",
            sections=sections,
        )

    def candidates(self, as_of, limit):
        raise AssertionError("read-only cockpit must not generate a candidate board")


class UnavailableValuation(Diagnosis):
    async def diagnose(self, symbol, as_of):
        result = await super().diagnose(symbol, as_of)
        sections = dict(result.sections)
        sections["valuation"] = DiagnosisSection(
            status="unavailable", source="fixture", explanation="missing",
        )
        return result.model_copy(update={"sections": sections, "overall_status": "partial"})


def advice(symbol, created_at=CUTOFF):
    evidence = EvidenceReference(
        evidence_id=f"e-{symbol}", source="fixture", snapshot_id="source-1",
        summary="fixture", observed_at=created_at,
    )
    return AdviceCard(
        advice_id=f"a-{symbol}", snapshot_id="cycle-1", asset=AssetKind.A_SHARE,
        symbol=symbol, horizon="intraday", observation_state="watch",
        action="observe", conclusion="observe", confidence=Decimal("0.5"),
        supporting_evidence=(evidence,), contrary_evidence=(), risks=("risk",),
        invalidation_conditions=("invalid",), quantitative_result={},
        strategy_version="v1", created_at=created_at,
    )


def aggregate(items):
    snapshot = DecisionCycleSnapshot(
        snapshot_id="cycle-1", trading_date=TRADE_DATE, phase="intraday", sequence=1,
        generated_at=CUTOFF, window_start=CUTOFF.replace(hour=5), window_end=CUTOFF,
        market_state="range", data_quality="ready", source_snapshot_ids=("source-1",),
        source_observed_at=(CUTOFF,), candidate_snapshot_id=None, news_event_ids=(),
        risk_event_ids=(), input_snapshot_hash="1" * 64, previous_snapshot_id=None,
        status="ready", ai_status="not_requested",
    )
    return DecisionCycleAggregate(
        snapshot=snapshot, advice=tuple(items), next_focus_due_at=CUTOFF,
        next_universe_due_at=CUTOFF,
    )


class Decisions:
    def cycles(self, trading_date=None, phase=None):
        return [aggregate((advice("600000"), advice("600519")))] if phase == "intraday" else []


class CorruptDecisions:
    def cycles(self, trading_date=None, phase=None):
        raise DecisionIntegrityError("corrupt advice payload")


def service(diagnosis=None, decisions=None):
    return StockDecisionCockpitService(
        Directory(), diagnosis or Diagnosis(), decisions or Decisions()
    )


@pytest.mark.asyncio
async def test_cockpit_filters_every_phase_and_evidence_to_selected_symbol() -> None:
    result = await service().get("600000", TRADE_DATE, CUTOFF)
    assert result.instrument.symbol == "600000"
    assert all(item.symbol == "600000" for phase in result.phases.values() for item in phase.advice)
    assert all(item.observed_at <= CUTOFF for item in result.all_evidence())
    assert result.phases["intraday"].change_stream[0].sequence == 1
    assert result.candidate_membership == ("short_term",)


@pytest.mark.asyncio
async def test_cockpit_degrades_only_failed_section() -> None:
    result = await service(diagnosis=UnavailableValuation()).get("600000", TRADE_DATE, CUTOFF)
    assert result.sections["valuation"].status == "unavailable"
    assert result.sections["market"].status == "ready"
    assert result.overall_quality == "partial"


@pytest.mark.asyncio
async def test_cockpit_never_guesses_funds_or_backtest() -> None:
    result = await service().get("600000", TRADE_DATE, CUTOFF)
    assert result.sections["funds"].reason == "fund_data_not_connected"
    assert result.sections["backtest"].reason == "backtest_not_run"


@pytest.mark.asyncio
async def test_cockpit_propagates_decision_integrity_error() -> None:
    with pytest.raises(DecisionIntegrityError):
        await service(decisions=CorruptDecisions()).get("600000", TRADE_DATE, CUTOFF)
