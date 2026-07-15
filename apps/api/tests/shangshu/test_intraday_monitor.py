from datetime import UTC, date, datetime, timedelta
import hashlib

from qibao_api.shangshu.intraday_monitor import (
    AdviceChangeDetector, IntradayEvaluationResult, IntradayMonitor,
    PollState, PollStateRepository,
)
from qibao_api.contracts.decision import (
    AdviceCard, DecisionCycleAggregate, DecisionCycleSnapshot, EvidenceReference,
)
from qibao_api.contracts.market import AssetKind
from decimal import Decimal
from qibao_api.bingbu.simulation_plan import QuantitativeLevels, SimulationGateContext
from qibao_api.gongbu.market_feed import MarketFeedSnapshot
from qibao_api.shangshu.decision_repository import DecisionRepository


NOW = datetime(2026, 7, 14, 2, 30, tzinfo=UTC)


class Calendar:
    def __init__(self, confirmed=True): self.confirmed = confirmed
    def is_trading_day(self, value: date): return self.confirmed and value == date(2026, 7, 14)


class Feed:
    def __init__(self):
        self.calls = []
        self.fail = False

    def snapshot_many(self, symbols, *, cutoff=None):
        self.calls.append((symbols, cutoff))
        if self.fail:
            raise RuntimeError("feed unavailable")
        return tuple(type("Quote", (), {"symbol": symbol, "observed_at": cutoff})() for symbol in symbols)


def monitor(tmp_path, *, feed=None, calendar=None):
    return IntradayMonitor(
        feed=feed or Feed(), calendar=calendar or Calendar(),
        state_repository=PollStateRepository(tmp_path / "poll.sqlite3"),
        focus_symbols=lambda now: ("000001",),
        universe_symbols=lambda now: ("300001", "123001"),
    )


def test_initial_due_schedule_and_restart_recovery(tmp_path) -> None:
    first = monitor(tmp_path)
    assert first.due(NOW) == frozenset({"focus", "universe"})
    result = first.check(NOW)
    assert result.polled == frozenset({"focus", "universe"})
    assert first.due(NOW + timedelta(seconds=59)) == frozenset()
    assert first.due(NOW + timedelta(seconds=60)) == frozenset({"focus"})
    assert first.due(NOW + timedelta(seconds=180)) == frozenset({"focus", "universe"})
    restarted = monitor(tmp_path)
    assert restarted.due(NOW + timedelta(seconds=60)) == frozenset({"focus"})


def test_failure_backoff_caps_and_success_resets(tmp_path) -> None:
    feed = Feed()
    feed.fail = True
    value = monitor(tmp_path, feed=feed)
    due = NOW
    expected = [60, 120, 240, 300]
    for seconds in expected:
        value.check(due, scopes=frozenset({"focus"}))
        state = value.state
        assert state.focus_interval_seconds == seconds
        assert state.mode == "degraded"
        assert state.last_error_code == "runtime_error"
        due = state.next_focus_due_at
    feed.fail = False
    value.check(due, scopes=frozenset({"focus"}))
    assert value.state.consecutive_focus_failures == 0
    assert value.state.focus_interval_seconds == 60


def test_no_poll_outside_window_or_unconfirmed_day(tmp_path) -> None:
    feed = Feed()
    value = monitor(tmp_path, feed=feed)
    assert value.check(datetime(2026, 7, 14, 1, 24, tzinfo=UTC)).polled == frozenset()
    assert monitor(tmp_path / "other", feed=feed, calendar=Calendar(False)).check(NOW).polled == frozenset()
    assert feed.calls == []


def test_universe_filters_convertible_bonds(tmp_path) -> None:
    feed = Feed()
    value = monitor(tmp_path, feed=feed)
    value.check(NOW, scopes=frozenset({"universe"}))
    assert feed.calls[0][0] == ("300001",)
    assert value.state_repository.snapshots() == [{
        "scope": "universe", "symbol": "300001",
        "observed_at": NOW.isoformat(), "source_snapshot_id": None,
    }]


def advice(advice_id="a1", **updates):
    evidence = EvidenceReference(
        evidence_id="e1", source="test", snapshot_id="s1", summary="factor",
        observed_at=NOW,
    )
    values = dict(
        advice_id=advice_id, snapshot_id="snapshot-1", asset=AssetKind.A_SHARE,
        symbol="000001", horizon="intraday", observation_state="candidate",
        action="observe", conclusion="unchanged", confidence=Decimal("0.5"),
        supporting_evidence=(evidence,), contrary_evidence=(), risks=("risk",),
        invalidation_conditions=("condition",), quantitative_result={"membership": "short_term"},
        strategy_version="v1", created_at=NOW,
    )
    values.update(updates)
    return AdviceCard(**values)


def test_advice_change_sets_previous_id_and_exact_sorted_fields() -> None:
    detector = AdviceChangeDetector()
    updated = detector.changed(
        advice(), advice("a2", action="wait", risks=("new risk",), conclusion="changed")
    )
    assert updated is not None
    assert updated.previous_advice_id == "a1"
    assert updated.changed_fields == ("action", "conclusion", "risks")
    assert detector.changed(updated, updated.model_copy(update={"advice_id": "a3"})) is None


def test_removed_candidate_is_invalidated_once_and_future_evidence_rejected() -> None:
    detector = AdviceChangeDetector()
    invalidated = detector.removed(advice(), "candidate_removed", NOW)
    assert invalidated is not None and invalidated.action == "invalidated"
    assert detector.removed(invalidated, "candidate_removed", NOW) is None
    future = advice("future", supporting_evidence=(
        EvidenceReference(
            evidence_id="e2", source="test", snapshot_id="s2", summary="future",
            observed_at=NOW + timedelta(seconds=1),
        ),
    ))
    import pytest
    with pytest.raises(ValueError, match="future evidence"):
        detector.validate_cutoff(future, NOW)


def test_success_batch_and_state_are_atomic_idempotent_and_restart_safe(tmp_path) -> None:
    database = tmp_path / "poll.sqlite3"
    repository = PollStateRepository(database)
    state = PollState(
        last_focus_success_at=NOW, next_focus_due_at=NOW + timedelta(seconds=60),
        next_universe_due_at=NOW,
    )
    snapshot = type("Quote", (), {
        "symbol": "000001", "observed_at": NOW, "source_snapshot_id": "q1",
    })()
    assert repository.append_success_batch("batch-1", "focus", (snapshot,), state, NOW)
    assert not repository.append_success_batch("batch-1", "focus", (snapshot,), state, NOW)
    reopened = PollStateRepository(database)
    assert reopened.latest() == state
    assert len(reopened.snapshots()) == 1


def test_constrained_budget_persists_300_second_universe_cadence(tmp_path) -> None:
    value = IntradayMonitor(
        feed=Feed(), calendar=Calendar(),
        state_repository=PollStateRepository(tmp_path / "budget.sqlite3"),
        focus_symbols=lambda now: (), universe_symbols=lambda now: ("300001",),
        source_budget=lambda now: "constrained",
    )
    value.check(NOW, scopes=frozenset({"universe"}))
    assert value.state.universe_interval_seconds == 300
    assert value.state.next_universe_due_at == NOW + timedelta(seconds=300)


def test_stream_selected_by_capability_does_not_poll(tmp_path) -> None:
    class StreamFeed:
        capabilities = frozenset({"subscribe"})

        def snapshot_many(self, symbols, *, cutoff=None):
            raise AssertionError("stream mode must not poll")

    value = IntradayMonitor(
        feed=StreamFeed(), calendar=Calendar(),
        state_repository=PollStateRepository(tmp_path / "stream.sqlite3"),
        focus_symbols=lambda now: ("000001",), universe_symbols=lambda now: ("300001",),
        delivery_mode="stream",
    )
    assert value.due(NOW) == frozenset()
    assert value.check(NOW).polled == frozenset()


class Evaluation:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def evaluate(self, context):
        self.calls.append(context)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


class InputPort:
    def __init__(self, value=None):
        self.value = value if value is not None else {"state": "ready"}

    def snapshot(self, *, now, cutoff):
        return self.value


class QuoteFeed:
    capabilities = frozenset({"snapshot", "snapshot_many"})

    def snapshot_many(self, symbols, *, cutoff=None):
        return tuple(MarketFeedSnapshot(
            symbol=symbol, price=Decimal("10"), change=Decimal("0"),
            change_percent=Decimal("0"), volume=Decimal("100"), source="test",
            observed_at=cutoff, fetched_at=cutoff, quality="ready",
            source_snapshot_id=f"quote-{symbol}-{int(cutoff.timestamp())}",
        ) for symbol in symbols)


def baseline_aggregate(repository):
    snapshot = DecisionCycleSnapshot(
        snapshot_id="premarket-1", trading_date=date(2026, 7, 14), phase="premarket",
        sequence=1, generated_at=datetime(2026, 7, 14, 1, 20, tzinfo=UTC),
        window_start=datetime(2026, 7, 14, 1, 0, tzinfo=UTC),
        window_end=datetime(2026, 7, 14, 1, 20, tzinfo=UTC), market_state="range",
        data_quality="ready", source_snapshot_ids=("source-1",),
        source_observed_at=(datetime(2026, 7, 14, 1, 20, tzinfo=UTC),),
        candidate_snapshot_id="candidates-1", news_event_ids=(), risk_event_ids=(),
        input_snapshot_hash=hashlib.sha256(b"premarket").hexdigest(),
        previous_snapshot_id=None, status="ready", ai_status="not_requested",
    )
    base = advice(snapshot_id="premarket-1",
                  created_at=datetime(2026, 7, 14, 1, 20, tzinfo=UTC),
                  supporting_evidence=(EvidenceReference(
                      evidence_id="base-e", source="test", snapshot_id="base-s",
                      summary="base", observed_at=datetime(2026, 7, 14, 1, 20, tzinfo=UTC),
                  ),))
    aggregate = DecisionCycleAggregate(snapshot=snapshot, advice=(base,))
    repository.append_cycle(aggregate)
    return aggregate


def decision_monitor(tmp_path, evaluation, repository):
    return IntradayMonitor(
        feed=QuoteFeed(), calendar=Calendar(),
        state_repository=PollStateRepository(tmp_path / "poll-decisions.sqlite3"),
        focus_symbols=lambda now: ("000001",), universe_symbols=lambda now: ("000001",),
        decision_repository=repository, evaluator=evaluation,
        candidate_factor_port=InputPort(), risk_port=InputPort(),
        compliance_port=InputPort(), evidence_port=InputPort(),
    )


def result_for(proposed=(), *, source="source-v1", gates=None):
    return IntradayEvaluationResult(
        advice=proposed, source_content={"version": source}, gates=gates or {},
        market_state="range", data_quality="ready", status="ready",
        candidate_snapshot_id="candidate-current", news_event_ids=(), risk_event_ids=(),
    )


def test_check_appends_changed_aggregate_then_unchanged_check_is_idempotent(tmp_path) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    baseline_aggregate(repository)
    proposed = advice("proposal", conclusion="changed", created_at=NOW)
    evaluation = Evaluation([result_for((proposed,)), result_for((proposed,))])
    monitor = decision_monitor(tmp_path, evaluation, repository)
    first = monitor.check(NOW)
    second = monitor.check(NOW + timedelta(seconds=180))
    cycles = repository.cycles(date(2026, 7, 14), "intraday")
    assert first.aggregate == cycles[0]
    assert second.aggregate == cycles[0]
    assert len(cycles) == 1
    assert cycles[0].advice[0].previous_advice_id == "a1"
    assert cycles[0].advice[0].changed_fields == ("conclusion",)


def test_changed_evaluator_output_with_same_source_content_appends(tmp_path) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    baseline_aggregate(repository)
    evaluation = Evaluation([
        result_for((advice("p1", conclusion="first", created_at=NOW),)),
        result_for((advice("p2", conclusion="second", created_at=NOW),)),
    ])
    monitor = decision_monitor(tmp_path, evaluation, repository)
    monitor.check(NOW)
    monitor.check(NOW + timedelta(seconds=180))
    cycles = repository.cycles(date(2026, 7, 14), "intraday")
    assert len(cycles) == 2
    assert cycles[1].advice[0].previous_advice_id == cycles[0].advice[0].advice_id
    assert cycles[1].advice[0].changed_fields == ("conclusion",)


def test_removed_candidate_invalidates_once(tmp_path) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    baseline_aggregate(repository)
    evaluation = Evaluation([result_for((), source="removed"), result_for((), source="removed")])
    monitor = decision_monitor(tmp_path, evaluation, repository)
    monitor.check(NOW)
    monitor.check(NOW + timedelta(seconds=180))
    cycles = repository.cycles(date(2026, 7, 14), "intraday")
    assert len(cycles) == 1
    assert cycles[0].advice[0].action == "invalidated"
    assert cycles[0].advice[0].quantitative_result["invalidation_reason_code"] == "candidate_removed"


def test_passing_gate_persists_reciprocal_simulation_plan(tmp_path) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    baseline_aggregate(repository)
    proposed = advice("proposal", conclusion="plan", created_at=NOW)
    gate = SimulationGateContext(
        quote_state="ready", compliance_state="ready", evidence_state="ready",
        risk_state="approve", advice_id="proposal", risk_decision_id="risk-1",
        compliance_snapshot_id="compliance-1", levels=QuantitativeLevels(
            watch_price_low=Decimal("9.9"), watch_price_high=Decimal("10.1"),
            stop_loss=Decimal("9.5"), take_profit=(Decimal("10.5"),),
            tranches=(Decimal("0.5"),), max_position=Decimal("0.5"),
            calculated_at=NOW, calculation_version="levels-v1",
        ),
    )
    monitor = decision_monitor(
        tmp_path, Evaluation([result_for((proposed,), gates={"proposal": gate})]), repository,
    )
    aggregate = monitor.check(NOW).aggregate
    assert aggregate is not None and len(aggregate.plans) == 1
    assert aggregate.advice[0].action == "simulated_plan"
    assert aggregate.advice[0].simulation_plan_id == aggregate.plans[0].plan_id
    assert aggregate.advice[0].risk_decision_id == aggregate.plans[0].risk_decision_id
