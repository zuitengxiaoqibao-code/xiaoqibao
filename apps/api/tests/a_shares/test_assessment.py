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
    risk_evidence = next(
        item for item in result.contrary_evidence
        if item.source == "fixture-risk"
    )
    assert "已触发明确阻断" in risk_evidence.summary
    assert "未触发明确阻断" not in risk_evidence.summary


def test_observes_complete_non_candidate_without_inventing_plan() -> None:
    result = DeterministicStockAssessor().assess("600519", sections(), (), CUTOFF)

    assert result.action == "observe"
    assert "simulation_eligible" not in result.model_dump(mode="json")


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
    assert "simulation_eligible" not in first.model_dump(mode="json")


def test_assessment_evidence_is_ordered_and_written_for_beginners() -> None:
    values = sections()
    values["market"] = section(
        "market",
        metrics={
            "price": "10.25",
            "change_percent": "1.49",
            "turnover_rate": "0.80",
        },
    )
    values["price_volume"] = section(
        "price_volume",
        metrics={"close": "10.25", "return_5d": "0.052", "volume_ratio": "1.18"},
    )

    result = DeterministicStockAssessor().assess(
        "600519", values, (), CUTOFF
    )

    assert [item.source for item in result.supporting_evidence[:3]] == [
        "fixture-market", "fixture-price_volume", "fixture-trend"
    ]
    assert result.supporting_evidence[0].summary == (
        "实时行情：现价 10.25 元，涨跌 1.49%，换手率 0.80%。"
    )
    assert result.supporting_evidence[1].summary == (
        "量价表现：收盘 10.25 元，近5日 5.20%，量比 1.18。"
    )
    assert not any(
        token in item.summary
        for item in result.supporting_evidence
        for token in ('{"', "fixture-", "change_percent", "return_5d")
    )


def test_assessment_identity_changes_with_frozen_source_evidence() -> None:
    first_sections = sections()
    second_sections = sections()
    first_sections["news"] = section("news").model_copy(update={
        "snapshot_id": "news-snapshot-1",
        "payload": {
            "metrics": {"event_count": 1, "adverse_event_count": 0},
            "evidence_ids": ["event-1"],
        },
    })
    second_sections["news"] = section("news").model_copy(update={
        "snapshot_id": "news-snapshot-2",
        "payload": {
            "metrics": {"event_count": 1, "adverse_event_count": 0},
            "evidence_ids": ["event-2"],
        },
    })

    first = DeterministicStockAssessor().assess(
        "600519", first_sections, (), CUTOFF
    )
    second = DeterministicStockAssessor().assess(
        "600519", second_sections, (), CUTOFF
    )

    first_news = next(item for item in first.supporting_evidence if item.source == "fixture-news")
    second_news = next(item for item in second.supporting_evidence if item.source == "fixture-news")
    assert first_news.evidence_id != second_news.evidence_id
    assert first.assessment_id != second.assessment_id


def test_missing_observation_is_a_risk_but_not_evidence() -> None:
    result = DeterministicStockAssessor().assess(
        "600519", sections(no_market=True), ("swing",), CUTOFF
    )

    assert result.action == "wait"
    assert "行情" in result.conclusion
    assert not any(item.source == "fixture-market" for item in result.contrary_evidence)
    assert any("缺失" in risk for risk in result.risks)
    assert "simulation_eligible" not in result.model_dump(mode="json")


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


def test_missing_market_remains_wait_even_when_many_sections_are_missing() -> None:
    values = sections(no_market=True, no_bars=True)
    values["risk"] = section("risk", metrics={"missing_section_count": 6})

    result = DeterministicStockAssessor().assess("600519", values, (), CUTOFF)

    assert result.action == "wait"
    assert result.confidence == Decimal("0.40")
    assert "行情" in result.conclusion
