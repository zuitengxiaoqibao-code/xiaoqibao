from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from qibao_api.contracts.decision import (
    AdviceCard,
    DecisionCycleAggregate,
    DecisionCycleSnapshot,
    EvidenceReference,
)
from qibao_api.contracts.market import AssetKind
from qibao_api.zhongshu.postclose_review import PostcloseReviewService


TRADING_DATE = date(2026, 7, 14)
CLOSE = datetime(2026, 7, 14, 7, 0, tzinfo=UTC)
NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


def _advice(advice_id: str, created_at: datetime, action: str = "observe") -> AdviceCard:
    return AdviceCard(
        advice_id=advice_id,
        snapshot_id=f"snapshot-{advice_id}",
        asset=AssetKind.A_SHARE,
        symbol="600000",
        horizon="intraday",
        observation_state="watching",
        action=action,
        conclusion="deterministic conclusion",
        confidence=Decimal("0.6"),
        supporting_evidence=(EvidenceReference(
            evidence_id=f"evidence-{advice_id}",
            source="fixture",
            snapshot_id=f"source-{advice_id}",
            summary="frozen evidence",
            observed_at=created_at,
        ),),
        contrary_evidence=(),
        risks=("price risk",),
        invalidation_conditions=("break support",),
        quantitative_result={},
        strategy_version="v1",
        created_at=created_at,
    )


def _cycle(advice: AdviceCard, phase: str = "premarket") -> DecisionCycleAggregate:
    snapshot = DecisionCycleSnapshot(
        snapshot_id=advice.snapshot_id,
        trading_date=TRADING_DATE,
        phase=phase,
        sequence=1,
        generated_at=advice.created_at,
        window_start=datetime(2026, 7, 13, 7, 0, tzinfo=UTC),
        window_end=advice.created_at,
        market_state="range",
        data_quality="ready",
        source_snapshot_ids=(f"source-{advice.advice_id}",),
        source_observed_at=(advice.created_at,),
        candidate_snapshot_id=None,
        news_event_ids=(),
        risk_event_ids=(),
        input_snapshot_hash="a" * 64,
        previous_snapshot_id=None,
        status="ready",
        ai_status="not_requested",
    )
    return DecisionCycleAggregate(snapshot=snapshot, advice=(advice,))


class Decisions:
    def __init__(self, cycles):
        self.values = list(cycles)
        self.appended = []

    def cycles(self, trading_date=None, phase=None):
        return [
            item for item in self.values
            if (trading_date is None or item.snapshot.trading_date == trading_date)
            and (phase is None or item.snapshot.phase == phase)
        ]

    def latest(self, trading_date, phase):
        values = self.cycles(trading_date, phase)
        return values[-1] if values else None

    def append_cycle(self, aggregate):
        self.appended.append(aggregate)
        self.values.append(aggregate)
        return True


class Outcomes:
    def __init__(self, values):
        self.values = values

    def list_market_outcomes(self, advice_ids, start, end):
        assert end == CLOSE
        return self.values


class Paper:
    def __init__(self, executions=(), decisions=()):
        self.executions = executions
        self.decisions = decisions

    def list_order_outcomes_between(self, start, end):
        assert end == CLOSE
        return list(self.executions)

    def list_risk_decisions(self, *, limit=50):
        return list(self.decisions)


class Audit:
    def __init__(self, findings=()):
        self.findings = findings

    def list_findings(self, *, asset):
        assert asset == AssetKind.A_SHARE
        return list(self.findings)


def _service(advice, market, *, executions=(), decisions=(), findings=()):
    repository = Decisions([_cycle(item) for item in advice])
    service = PostcloseReviewService(
        decision_repository=repository,
        market_outcome_source=Outcomes(market),
        paper_repository=Paper(executions, decisions),
        audit_repository=Audit(findings),
    )
    return service, repository


def test_reviews_only_frozen_advice_and_uses_observations_through_close() -> None:
    frozen = _advice("frozen", datetime(2026, 7, 14, 1, 30, tzinfo=UTC))
    late = _advice("late", datetime(2026, 7, 14, 7, 1, tzinfo=UTC))
    service, repository = _service(
        (frozen, late),
        (
            {"advice_id": "frozen", "observed_at": datetime(2026, 7, 14, 6, 59, tzinfo=UTC),
             "available": True, "direction": "favorable", "invalidation_triggered": False},
            {"advice_id": "frozen", "observed_at": datetime(2026, 7, 14, 7, 1, tzinfo=UTC),
             "available": True, "direction": "adverse", "invalidation_triggered": True},
        ),
    )

    result = service.run(TRADING_DATE, NOW)

    assert [(item.advice_id, item.status, item.attribution) for item in result.outcomes] == [
        ("frozen", "correct", "trend_failure")
    ]
    assert result.outcomes[0].original_snapshot_id == frozen.snapshot_id
    assert len(result.outcomes[0].outcome_input_hash) == 64
    assert result.next_day_observations == ("frozen",)
    assert repository.appended == [result.aggregate]
    assert result.aggregate.snapshot.phase == "postclose"


def test_unavailable_market_data_is_unverifiable_and_can_remain_observed() -> None:
    advice = _advice("missing", datetime(2026, 7, 14, 2, 0, tzinfo=UTC))
    service, _ = _service((advice,), ())

    result = service.run(TRADING_DATE, NOW)

    outcome = result.outcomes[0]
    assert (outcome.status, outcome.attribution) == ("unverifiable", "data_unavailable")
    assert outcome.withdrawal_reason is None
    assert result.next_day_observations == ("missing",)


def test_same_frozen_inputs_do_not_append_a_new_cycle_on_later_rerun() -> None:
    advice = _advice("stable", datetime(2026, 7, 14, 2, 0, tzinfo=UTC))
    service, repository = _service((advice,), ({
        "advice_id": "stable",
        "observed_at": CLOSE,
        "available": True,
        "direction": "favorable",
        "invalidation_triggered": False,
    },))

    first = service.run(TRADING_DATE, NOW)
    second = service.run(TRADING_DATE, datetime(2026, 7, 14, 9, 0, tzinfo=UTC))

    assert second.aggregate.snapshot.snapshot_id == first.aggregate.snapshot.snapshot_id
    assert len(repository.appended) == 1


def test_provider_order_does_not_change_latest_outcome_or_hash() -> None:
    advice = _advice("ordered", datetime(2026, 7, 14, 2, 0, tzinfo=UTC))
    earlier = {"advice_id": "ordered", "outcome_id": "outcome-a",
               "observed_at": datetime(2026, 7, 14, 6, 0, tzinfo=UTC),
               "available": True, "direction": "adverse", "invalidation_triggered": False}
    later_a = {"advice_id": "ordered", "outcome_id": "outcome-a",
               "observed_at": CLOSE, "available": True, "direction": "adverse",
               "invalidation_triggered": False}
    later_b = {"advice_id": "ordered", "outcome_id": "outcome-b",
               "observed_at": CLOSE, "available": True, "direction": "favorable",
               "invalidation_triggered": False}
    first, _ = _service((advice,), (later_b, earlier, later_a))
    second, _ = _service((advice,), (later_a, later_b, earlier))

    first_outcome = first.run(TRADING_DATE, NOW).outcomes[0]
    second_outcome = second.run(TRADING_DATE, NOW).outcomes[0]

    assert first_outcome.status == second_outcome.status == "correct"
    assert first_outcome.outcome_input_hash == second_outcome.outcome_input_hash


def test_excludes_backdated_advice_from_snapshot_frozen_after_close() -> None:
    advice = _advice("backdated", datetime(2026, 7, 14, 2, 0, tzinfo=UTC))
    cycle = _cycle(advice).model_copy(update={
        "snapshot": _cycle(advice).snapshot.model_copy(update={
            "generated_at": datetime(2026, 7, 14, 7, 1, tzinfo=UTC),
        }),
    })
    repository = Decisions([cycle])
    service = PostcloseReviewService(
        decision_repository=repository, market_outcome_source=Outcomes(()),
        paper_repository=Paper(), audit_repository=Audit(),
    )

    result = service.run(TRADING_DATE, NOW)

    assert result.outcomes == ()
    assert result.aggregate.advice == ()


def test_rejects_conflicting_duplicate_frozen_advice_ids() -> None:
    first = _advice("duplicate", datetime(2026, 7, 14, 2, 0, tzinfo=UTC))
    second = first.model_copy(update={"conclusion": "changed conclusion"})
    repository = Decisions([_cycle(first), _cycle(second, "intraday")])
    service = PostcloseReviewService(
        decision_repository=repository, market_outcome_source=Outcomes(()),
        paper_repository=Paper(), audit_repository=Audit(),
    )

    with pytest.raises(ValueError, match="conflicting duplicate advice_id"):
        service.run(TRADING_DATE, NOW)


def test_input_reversion_creates_a_new_append_only_snapshot_identity() -> None:
    advice = _advice("reversion", datetime(2026, 7, 14, 2, 0, tzinfo=UTC))
    market = [{"advice_id": "reversion", "outcome_id": "state-a", "observed_at": CLOSE,
               "available": True, "direction": "favorable", "invalidation_triggered": False}]
    service, repository = _service((advice,), market)
    first = service.run(TRADING_DATE, NOW)
    market[0] = {**market[0], "outcome_id": "state-b", "direction": "adverse"}
    second = service.run(TRADING_DATE, NOW)
    market[0] = {**market[0], "outcome_id": "state-a", "direction": "favorable"}

    third = service.run(TRADING_DATE, NOW)

    assert len({first.aggregate.snapshot.snapshot_id,
                second.aggregate.snapshot.snapshot_id,
                third.aggregate.snapshot.snapshot_id}) == 3
    assert third.aggregate.snapshot.previous_snapshot_id == second.aggregate.snapshot.snapshot_id


def test_snapshot_metadata_uses_only_attributed_inputs_inside_advice_window() -> None:
    advice = _advice("bounded", datetime(2026, 7, 14, 1, 0, tzinfo=UTC))
    before = datetime(2026, 7, 14, 1, 20, tzinfo=UTC)
    inside = datetime(2026, 7, 14, 4, 0, tzinfo=UTC)
    service, _ = _service((advice,), (
        {"advice_id": "bounded", "outcome_id": "too-early", "observed_at": before,
         "available": True, "direction": "adverse", "invalidation_triggered": False},
        {"advice_id": "other", "outcome_id": "unattributed", "observed_at": CLOSE,
         "available": True, "direction": "adverse", "invalidation_triggered": False},
        {"advice_id": "bounded", "outcome_id": "inside", "observed_at": inside,
         "available": True, "direction": "favorable", "invalidation_triggered": False},
    ))

    result = service.run(TRADING_DATE, NOW)

    assert result.aggregate.snapshot.source_observed_at == (inside,)


def test_wrong_invalidated_and_risk_blocked_advice_are_withdrawn() -> None:
    created = datetime(2026, 7, 14, 2, 0, tzinfo=UTC)
    advice = tuple(_advice(value, created) for value in ("wrong", "invalid", "blocked"))
    service, _ = _service(
        advice,
        (
            {"advice_id": "wrong", "observed_at": CLOSE, "available": True,
             "direction": "adverse", "invalidation_triggered": False},
            {"advice_id": "invalid", "observed_at": CLOSE, "available": True,
             "direction": "adverse", "invalidation_triggered": True},
            {"advice_id": "blocked", "observed_at": CLOSE, "available": True,
             "direction": "favorable", "invalidation_triggered": False},
        ),
        decisions=({"decision_id": "risk-1", "advice_id": "blocked",
                    "outcome": "reject", "decided_at": CLOSE},),
    )

    result = service.run(TRADING_DATE, NOW)

    assert [item.status for item in result.outcomes] == ["risk_blocked", "invalidated", "wrong"]
    assert all(item.withdrawal_reason for item in result.outcomes)
    assert result.next_day_observations == ()
    assert all(item.action == "invalidated" for item in result.aggregate.advice)
