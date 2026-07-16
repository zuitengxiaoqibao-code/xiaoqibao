from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
import pytest

from qibao_api.a_shares.cockpit import StockDecisionCockpitService
from qibao_api.a_shares.diagnosis import (
    AShareDiagnosis,
    AShareDiagnosisService,
    DiagnosisSection,
)
from qibao_api.a_shares.fundamentals import FundamentalSnapshot
from qibao_api.a_shares.instrument_directory import AShareInstrument
from qibao_api.a_shares.preparation import PreparationSource, StockPreparation
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
    def resolve_at(self, symbol, cutoff):
        assert cutoff == CUTOFF
        if symbol != "600000":
            return None
        return AShareInstrument(
            symbol=symbol, name="浦发银行", exchange="sh",
            observed_at=CUTOFF, quote_quality="ready",
        )


class AcceptanceDirectory:
    def resolve_at(self, symbol, cutoff):
        assert cutoff == CUTOFF
        names = {
            "600000": "浦发银行",
            "600519": "贵州茅台",
            "000001": "平安银行",
        }
        if symbol not in names:
            return None
        return AShareInstrument(
            symbol=symbol, name=names[symbol], exchange="sz" if symbol.startswith("0") else "sh",
            observed_at=CUTOFF, quote_quality="ready",
        )


class Diagnosis:
    async def diagnose(self, symbol, as_of, *, persist=True, cutoff=None):
        assert persist is False
        sections = {
            name: DiagnosisSection(
                status="ready", observed_at=CUTOFF, source="fixture",
                metrics={"symbol": symbol}, explanation="fixture",
            )
            for name in (
                "market", "price_volume", "trend", "valuation", "fundamentals",
                "funds", "events", "industry", "risk",
            )
        }
        return AShareDiagnosis(
            symbol=symbol, as_of=as_of, action="observe", overall_status="ready",
            sections=sections,
        )

    def candidates(self, as_of, limit):
        raise AssertionError("read-only cockpit must not generate a candidate board")


class UnavailableValuation(Diagnosis):
    async def diagnose(self, symbol, as_of, *, persist=True, cutoff=None):
        result = await super().diagnose(symbol, as_of, persist=persist, cutoff=cutoff)
        sections = dict(result.sections)
        sections["valuation"] = DiagnosisSection(
            status="unavailable", source="fixture", explanation="missing",
        )
        return result.model_copy(update={"sections": sections, "overall_status": "partial"})


class QuoteObservedDuringRequest(Diagnosis):
    async def diagnose(self, symbol, as_of, *, persist=True, cutoff=None):
        result = await super().diagnose(symbol, as_of, persist=persist, cutoff=cutoff)
        sections = dict(result.sections)
        sections["market"] = sections["market"].model_copy(
            update={"observed_at": CUTOFF.replace(second=2)}
        )
        return result.model_copy(update={"sections": sections})


class DateObservedDiagnosis(Diagnosis):
    async def diagnose(self, symbol, as_of, *, persist=True, cutoff=None):
        result = await super().diagnose(
            symbol, as_of, persist=persist, cutoff=cutoff
        )
        sections = {
            name: section.model_copy(update={"observed_at": as_of})
            for name, section in result.sections.items()
        }
        return result.model_copy(update={"sections": sections})


class ChangedMarketDiagnosis(Diagnosis):
    async def diagnose(self, symbol, as_of, *, persist=True, cutoff=None):
        result = await super().diagnose(symbol, as_of, persist=persist, cutoff=cutoff)
        sections = dict(result.sections)
        sections["market"] = sections["market"].model_copy(
            update={"metrics": {"symbol": symbol, "price": "12.34"}}
        )
        return result.model_copy(update={"sections": sections})


class ChangedExplanationDiagnosis(Diagnosis):
    async def diagnose(self, symbol, as_of, *, persist=True, cutoff=None):
        result = await super().diagnose(symbol, as_of, persist=persist, cutoff=cutoff)
        sections = dict(result.sections)
        sections["market"] = sections["market"].model_copy(
            update={"explanation": "changed visible explanation"}
        )
        return result.model_copy(update={"sections": sections})


class FundFlowDiagnosis(Diagnosis):
    async def diagnose(self, symbol, as_of, *, persist=True, cutoff=None):
        result = await super().diagnose(
            symbol, as_of, persist=persist, cutoff=cutoff
        )
        sections = dict(result.sections)
        sections["funds"] = DiagnosisSection(
            status="ready",
            observed_at=CUTOFF,
            source="eastmoney-fund-flow",
            metrics={
                "latest_trade_date": TRADE_DATE.isoformat(),
                "main_net_5d": Decimal("350000000"),
                "flow_direction": "inflow",
            },
            evidence_ids=("fund-flow-" + "c" * 24,),
            explanation="verified fund flow",
        )
        return result.model_copy(update={"sections": sections})


class RecordingHistoricalDiagnosis(Diagnosis):
    def __init__(self):
        self.cutoff = None

    async def diagnose(self, symbol, as_of, *, persist=True, cutoff=None):
        self.cutoff = cutoff
        return await super().diagnose(symbol, as_of, persist=persist, cutoff=cutoff)


@pytest.mark.asyncio
async def test_historical_cockpit_pushes_cutoff_into_diagnosis() -> None:
    diagnosis = RecordingHistoricalDiagnosis()

    await service(diagnosis=diagnosis).get(
        "600000", date(2026, 7, 14), CUTOFF
    )

    assert diagnosis.cutoff == CUTOFF


def advice(symbol, created_at=CUTOFF, action="observe"):
    evidence = EvidenceReference(
        evidence_id=f"e-{symbol}", source="fixture", snapshot_id="source-1",
        summary="fixture", observed_at=created_at,
    )
    return AdviceCard(
        advice_id=f"a-{symbol}", snapshot_id="cycle-1", asset=AssetKind.A_SHARE,
        symbol=symbol, horizon="intraday", observation_state="watch",
        action=action, conclusion="observe", confidence=Decimal("0.5"),
        supporting_evidence=(evidence,), contrary_evidence=(), risks=("risk",),
        invalidation_conditions=("invalid",), quantitative_result={},
        strategy_version="v1", created_at=created_at,
    )


def aggregate(items, *, source_observed_at=CUTOFF, sequence=1, plans=()):
    snapshot = DecisionCycleSnapshot(
        snapshot_id=f"cycle-{sequence}", trading_date=TRADE_DATE,
        phase="intraday", sequence=sequence,
        generated_at=CUTOFF, window_start=CUTOFF.replace(hour=5), window_end=CUTOFF,
        market_state="range", data_quality="ready", source_snapshot_ids=("source-1",),
        source_observed_at=(source_observed_at,), candidate_snapshot_id=None,
        news_event_ids=(), risk_event_ids=(), input_snapshot_hash="1" * 64,
        previous_snapshot_id=None if sequence == 1 else "cycle-1",
        status="ready", ai_status="not_requested",
    )
    return DecisionCycleAggregate(
        snapshot=snapshot, advice=tuple(items), plans=tuple(plans), next_focus_due_at=CUTOFF,
        next_universe_due_at=CUTOFF,
    )


class Decisions:
    def cycles(self, trading_date=None, phase=None):
        return [aggregate((advice("600000"), advice("600519")))] if phase == "intraday" else []


class CorruptDecisions:
    def cycles(self, trading_date=None, phase=None):
        raise DecisionIntegrityError("corrupt advice payload")


class ReadOnlyPreparation:
    def __init__(self):
        self.inspections = []

    async def inspect(self, symbol, *, as_of, cutoff=None):
        self.inspections.append((symbol, as_of, cutoff))
        return StockPreparation(
            symbol=symbol, status="ready", refreshed=False,
            sources=tuple(
                PreparationSource(name=name, status="ready")
                for name in ("quote", "history", "finance", "news")
            ),
            started_at=CUTOFF, completed_at=CUTOFF,
        )

    async def prepare(self, *args, **kwargs):
        raise AssertionError("cockpit GET must not mutate preparation sources")


def service(diagnosis=None, decisions=None, clock=lambda: CUTOFF, preparation=None):
    return StockDecisionCockpitService(
        Directory(), diagnosis or Diagnosis(), decisions or Decisions(),
        preparation or ReadOnlyPreparation(), clock=clock,
    )


@pytest.mark.asyncio
async def test_cockpit_uses_read_only_preparation_inspection() -> None:
    preparation = ReadOnlyPreparation()

    result = await service(preparation=preparation).get("600000", TRADE_DATE, CUTOFF)

    assert result.preparation.refreshed is False
    assert preparation.inspections == [("600000", TRADE_DATE, None)]


class Explainer:
    async def explain(self, assessment, evidence):
        from qibao_api.a_shares.assessment_ai import AssessmentAIResult

        assert {item.evidence_id for item in evidence} == {
            item.evidence_id
            for item in (*assessment.supporting_evidence, *assessment.contrary_evidence)
        }
        return AssessmentAIResult(
            status="invalid", assessment=assessment, explanation=None
        )


@pytest.mark.asyncio
async def test_cockpit_exposes_ai_status_without_changing_assessment() -> None:
    plain = await service().get("600000", TRADE_DATE, CUTOFF)
    with_ai = StockDecisionCockpitService(
        Directory(), Diagnosis(), Decisions(), ReadOnlyPreparation(),
        assessor_ai=Explainer(), clock=lambda: CUTOFF
    )

    result = await with_ai.get("600000", TRADE_DATE, CUTOFF)

    assert result.ai_status == "invalid"
    assert result.ai_explanation is None
    assert result.assessment == plain.assessment


@pytest.mark.asyncio
async def test_cockpit_filters_every_phase_and_evidence_to_selected_symbol() -> None:
    result = await service().get("600000", TRADE_DATE, CUTOFF)
    assert result.instrument.symbol == "600000"
    assert all(item.symbol == "600000" for phase in result.phases.values() for item in phase.advice)
    assert all(item.observed_at <= CUTOFF for item in result.all_evidence())
    assert result.phases["intraday"].change_stream[0].sequence == 1
    assert result.candidate_membership == ("short_term",)
    assert result.assessment.symbol == "600000"
    assert "simulation_eligible" not in result.assessment.model_dump(mode="json")


@pytest.mark.asyncio
async def test_read_only_diagnosis_sections_produce_content_addressed_evidence() -> None:
    first = await service().get("600000", TRADE_DATE, CUTOFF)
    second = await service().get("600000", TRADE_DATE, CUTOFF)
    changed = await service(diagnosis=ChangedMarketDiagnosis()).get(
        "600000", TRADE_DATE, CUTOFF
    )
    changed_explanation = await service(diagnosis=ChangedExplanationDiagnosis()).get(
        "600000", TRADE_DATE, CUTOFF
    )

    evidenced_sections = {
        name
        for name, section in first.sections.items()
        if section.status == "ready" and section.observed_at is not None
    }
    assert all(first.sections[name].snapshot_id for name in evidenced_sections)
    assert len(first.assessment.supporting_evidence) == len(evidenced_sections)
    assert {
        item.snapshot_id for item in first.assessment.supporting_evidence
    } == {first.sections[name].snapshot_id for name in evidenced_sections}
    assert {
        name: first.sections[name].snapshot_id for name in evidenced_sections
    } == {
        name: second.sections[name].snapshot_id for name in evidenced_sections
    }
    assert (
        changed.sections["market"].snapshot_id
        != first.sections["market"].snapshot_id
    )
    assert (
        changed_explanation.sections["market"].snapshot_id
        != first.sections["market"].snapshot_id
    )
    assert not any(
        risk.startswith("source_snapshot_unavailable:")
        for risk in first.assessment.risks
    )


@pytest.mark.asyncio
async def test_cockpit_degrades_only_failed_section() -> None:
    result = await service(diagnosis=UnavailableValuation()).get("600000", TRADE_DATE, CUTOFF)
    assert result.sections["valuation"].status == "unavailable"
    assert result.sections["market"].status == "ready"
    assert result.overall_quality == "partial"


@pytest.mark.asyncio
async def test_cockpit_maps_verified_fund_flow_section() -> None:
    result = await service(diagnosis=FundFlowDiagnosis()).get(
        "600000", TRADE_DATE, CUTOFF
    )

    assert result.sections["funds"].source == "eastmoney-fund-flow"
    assert result.sections["funds"].payload["metrics"]["main_net_5d"] == Decimal(
        "350000000"
    )
    assert result.sections["funds"].payload["evidence_ids"] == (
        "fund-flow-" + "c" * 24,
    )


@pytest.mark.asyncio
async def test_live_cockpit_extends_cutoff_to_quote_observed_during_request() -> None:
    completed_at = CUTOFF.replace(second=3)
    result = await service(
        diagnosis=QuoteObservedDuringRequest(), clock=lambda: completed_at
    ).get("600000", TRADE_DATE, CUTOFF)

    assert result.cutoff == completed_at
    assert result.sections["market"].observed_at == CUTOFF.replace(second=2)


@pytest.mark.asyncio
async def test_live_cockpit_treats_date_evidence_as_beijing_day_start() -> None:
    as_of = date(2026, 7, 17)
    cutoff = datetime(2026, 7, 16, 16, 8, tzinfo=timezone.utc)

    class MidnightDirectory:
        def resolve_at(self, symbol, requested_cutoff):
            assert requested_cutoff == cutoff
            return AShareInstrument(
                symbol=symbol,
                name="贵州茅台",
                exchange="sh",
                observed_at=cutoff,
                quote_quality="ready",
            )

    cockpit = StockDecisionCockpitService(
        MidnightDirectory(),
        DateObservedDiagnosis(),
        Decisions(),
        ReadOnlyPreparation(),
        clock=lambda: cutoff,
    )

    result = await cockpit.get("600519", as_of, cutoff)

    assert result.sections["trend"].status == "ready"
    assert result.sections["risk"].status == "ready"
    assert result.sections["trend"].observed_at == datetime(
        2026, 7, 17, tzinfo=ZoneInfo("Asia/Shanghai")
    )


@pytest.mark.asyncio
async def test_historical_cockpit_keeps_strict_requested_cutoff() -> None:
    historical_date = TRADE_DATE.replace(day=14)
    result = await service(clock=lambda: CUTOFF.replace(hour=8)).get(
        "600000", historical_date, CUTOFF
    )

    assert result.cutoff == CUTOFF


@pytest.mark.asyncio
async def test_live_cockpit_rejects_observation_after_completion() -> None:
    result = await service(
        diagnosis=QuoteObservedDuringRequest(), clock=lambda: CUTOFF.replace(second=1)
    ).get("600000", TRADE_DATE, CUTOFF)

    assert result.cutoff == CUTOFF.replace(second=1)
    assert result.sections["market"].status == "unavailable"
    assert result.sections["market"].reason == "observed_after_cutoff"


@pytest.mark.asyncio
async def test_cockpit_keeps_funds_and_omits_removed_backtest_section() -> None:
    result = await service().get("600000", TRADE_DATE, CUTOFF)
    assert "funds" in result.sections
    assert "backtest" not in result.sections


@pytest.mark.asyncio
async def test_cockpit_propagates_decision_integrity_error() -> None:
    with pytest.raises(DecisionIntegrityError):
        await service(decisions=CorruptDecisions()).get("600000", TRADE_DATE, CUTOFF)


class MixedAssetDecisions:
    def cycles(self, trading_date=None, phase=None):
        if phase != "intraday":
            return []
        bond = advice("600000").model_copy(update={"asset": AssetKind.CONVERTIBLE_BOND})
        value = aggregate((advice("600000"),))
        return [value.model_copy(update={"advice": (advice("600000"), bond)})]


@pytest.mark.asyncio
async def test_cockpit_excludes_same_symbol_non_a_share_advice() -> None:
    result = await service(decisions=MixedAssetDecisions()).get(
        "600000", TRADE_DATE, CUTOFF
    )
    assert len(result.phases["intraday"].advice) == 1
    assert result.phases["intraday"].advice[0].asset == AssetKind.A_SHARE


class OtherStockDecisions:
    def cycles(self, trading_date=None, phase=None):
        if phase != "intraday":
            return []
        return [aggregate((advice("600519"),))]


@pytest.mark.asyncio
async def test_cockpit_preserves_phase_version_when_selected_stock_was_not_included() -> None:
    result = await service(decisions=OtherStockDecisions()).get(
        "600000", TRADE_DATE, CUTOFF
    )

    assert result.phases["intraday"].advice == ()
    assert len(result.phases["intraday"].change_stream) == 1


class FutureSourceDecisions:
    def cycles(self, trading_date=None, phase=None):
        if phase != "intraday":
            return []
        value = aggregate((advice("600000"),))
        snapshot = value.snapshot.model_copy(update={
            "source_observed_at": (CUTOFF.replace(hour=7),)
        })
        return [value.model_copy(update={"snapshot": snapshot})]


@pytest.mark.asyncio
async def test_cockpit_excludes_cycle_with_source_observed_after_cutoff() -> None:
    result = await service(decisions=FutureSourceDecisions()).get(
        "600000", TRADE_DATE, CUTOFF
    )
    assert result.phases["intraday"].advice == ()
    assert result.phases["intraday"].change_stream == ()


class InvalidatedDecisions:
    def cycles(self, trading_date=None, phase=None):
        if phase != "intraday":
            return []
        first = advice("600000", CUTOFF.replace(hour=5))
        removed = advice("600000", CUTOFF, action="invalidated").model_copy(
            update={"previous_advice_id": first.advice_id}
        )
        return [aggregate((first,)), aggregate((removed,), sequence=2)]


@pytest.mark.asyncio
async def test_latest_invalidation_removes_current_advice_and_membership() -> None:
    result = await service(decisions=InvalidatedDecisions()).get(
        "600000", TRADE_DATE, CUTOFF
    )
    assert result.current_advice == ()
    assert result.candidate_membership == ()
    assert "simulation_eligible" not in result.assessment.model_dump(mode="json")


class NoBars:
    def latest_many(self, symbols, limit, as_of):
        return {symbol: [] for symbol in symbols}


class UnavailableMarket:
    async def fetch_snapshot(self, symbol):
        raise RuntimeError("market unavailable")


class AvailableFinance:
    def fetch(self, symbol):
        return FundamentalSnapshot(
            symbol=symbol, observed_at=CUTOFF.replace(hour=5),
            report_period=TRADE_DATE, industry="银行", eps=Decimal("1"),
            source="fixture-finance",
        )


class EmptyNews:
    def events(self):
        return []

    def effective_events(self, *, cutoff=None):
        return []


@pytest.mark.asyncio
async def test_cockpit_keeps_finance_and_news_when_market_and_bars_are_unavailable() -> None:
    diagnosis = AShareDiagnosisService(
        bar_repository=NoBars(), market_source=UnavailableMarket(),
        finance_source=AvailableFinance(), news_repository=EmptyNews(),
    )

    result = await service(diagnosis=diagnosis).get("600000", TRADE_DATE, CUTOFF)

    assert result.sections["market"].status == "unavailable"
    assert result.sections["price_volume"].status == "unavailable"
    assert result.sections["fundamentals"].status == "ready"
    assert result.sections["news"].status == "ready"
    assert result.sections["industry"].status == "unavailable"
