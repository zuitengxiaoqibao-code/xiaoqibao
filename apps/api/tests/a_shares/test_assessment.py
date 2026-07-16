from datetime import datetime, timezone
from decimal import Decimal

from qibao_api.a_shares.assessment import DeterministicStockAssessor
from qibao_api.a_shares.cockpit import CockpitSection


CUTOFF = datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)


def section(
    name: str,
    *,
    status: str = "ready",
    observed_at: datetime | None = CUTOFF,
    metrics: dict | None = None,
) -> CockpitSection:
    return CockpitSection(
        status=status,
        source=f"fixture-{name}",
        observed_at=observed_at,
        snapshot_id=f"snapshot-{name}",
        reason=None if status == "ready" else f"{name}_unavailable",
        payload={"metrics": metrics or {"section": name}},
    )


def sections(*, no_bars: bool = False, risk: str = "ready", no_market: bool = False):
    result = {
        name: section(name)
        for name in (
            "market", "price_volume", "trend", "valuation", "fundamentals",
            "funds", "news", "industry", "risk", "backtest",
        )
    }
    if no_bars:
        result["trend"] = section("trend", status="unavailable", observed_at=None)
    if no_market:
        result["market"] = section("market", status="unavailable", observed_at=None)
    if risk == "blocked":
        result["risk"] = section(
            "risk", status="blocked", metrics={"decision": "blocked"}
        )
    return result


def test_waits_when_trend_sample_is_unavailable() -> None:
    result = DeterministicStockAssessor().assess("600519", sections(no_bars=True), (), CUTOFF)

    assert result.action == "wait"
    assert "日线" in result.conclusion


def test_avoids_when_authoritative_risk_is_blocked() -> None:
    result = DeterministicStockAssessor().assess(
        "600519", sections(no_bars=True, risk="blocked"), (), CUTOFF
    )

    assert result.action == "avoid"


def test_observes_complete_non_candidate_without_inventing_plan() -> None:
    result = DeterministicStockAssessor().assess("600519", sections(), (), CUTOFF)

    assert result.action == "observe"
    assert result.simulation_eligible is False


def test_assessment_evidence_is_deterministic_and_cutoff_traceable() -> None:
    assessor = DeterministicStockAssessor()

    first = assessor.assess("600519", sections(), ("short_term",), CUTOFF)
    second = assessor.assess("600519", sections(), ("short_term",), CUTOFF)

    assert first == second
    assert first.generated_at == CUTOFF
    assert first.confidence == Decimal("0.75")
    assert first.supporting_evidence
    assert all(item.observed_at <= CUTOFF for item in first.supporting_evidence)
    assert all(item.source.startswith("fixture-") for item in first.supporting_evidence)
    assert len({item.evidence_id for item in first.supporting_evidence}) == len(
        first.supporting_evidence
    )
    assert first.simulation_eligible is False


def test_missing_observation_is_a_risk_but_not_evidence() -> None:
    result = DeterministicStockAssessor().assess(
        "600519", sections(no_market=True), ("swing",), CUTOFF
    )

    assert result.action == "wait"
    assert "行情" in result.conclusion
    assert not any(item.source == "fixture-market" for item in result.contrary_evidence)
    assert any("缺失" in risk for risk in result.risks)
    assert result.simulation_eligible is False


def test_future_source_observation_never_enters_assessment_evidence() -> None:
    values = sections()
    values["market"] = section(
        "market", observed_at=CUTOFF.replace(hour=7), metrics={"price": "future"}
    )

    result = DeterministicStockAssessor().assess("600519", values, (), CUTOFF)

    assert result.action == "wait"
    assert not any(item.source == "fixture-market" for item in result.supporting_evidence)
    assert "future" not in "".join(item.summary for item in result.supporting_evidence)


def test_observed_section_without_source_snapshot_is_an_explicit_risk() -> None:
    values = sections()
    values["valuation"] = section("valuation").model_copy(update={"snapshot_id": None})

    result = DeterministicStockAssessor().assess("600519", values, (), CUTOFF)

    assert not any(item.source == "fixture-valuation" for item in result.supporting_evidence)
    assert "source_snapshot_unavailable:valuation" in result.risks
    assert "source_snapshot_unavailable:valuation" in result.invalidation_conditions


def test_production_risk_metrics_and_adverse_evidence_trigger_avoid() -> None:
    values = sections()
    values["risk"] = section("risk", metrics={"missing_section_count": 3})
    values["trend"] = section(
        "trend", metrics={"volatility_20d": "0.09", "drawdown_60d": "-0.24"}
    )
    values["news"] = section("news", status="partial", metrics={"adverse_event_count": 1})

    result = DeterministicStockAssessor().assess("600519", values, (), CUTOFF)

    assert result.action == "avoid"
    assert result.confidence != Decimal("0.75")
    assert any("回撤" in risk or "波动" in risk or "缺失" in risk for risk in result.risks)
