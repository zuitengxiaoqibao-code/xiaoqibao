from datetime import UTC, date, datetime, timedelta

from qibao_api.shangshu.intraday_monitor import (
    AdviceChangeDetector, IntradayMonitor, PollStateRepository,
)
from qibao_api.contracts.decision import AdviceCard, EvidenceReference
from qibao_api.contracts.market import AssetKind
from decimal import Decimal


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
