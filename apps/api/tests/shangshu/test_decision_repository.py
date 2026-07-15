import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from qibao_api.contracts.decision import (
    AdviceCard, DecisionCycleAggregate, DecisionCycleSnapshot, EvidenceReference, SimulationPlan,
)
from qibao_api.shangshu.decision_repository import DecisionIntegrityError, DecisionRepository


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 7, 15, 9, 20, tzinfo=TZ)
TRADE_DATE = date(2026, 7, 15)


def aggregate(sequence: int = 1, previous: str | None = None, *, planned: bool = False) -> DecisionCycleAggregate:
    snapshot_id = f"cycle-{sequence}"
    snapshot = DecisionCycleSnapshot(
        snapshot_id=snapshot_id, trading_date=TRADE_DATE, phase="premarket", sequence=sequence,
        generated_at=NOW + timedelta(minutes=sequence), window_start=NOW - timedelta(hours=1),
        window_end=NOW, market_state="range", data_quality="ready",
        source_snapshot_ids=("source-1",), source_observed_at=(NOW,), candidate_snapshot_id=None,
        news_event_ids=(), risk_event_ids=(), input_snapshot_hash=str(sequence) * 64,
        previous_snapshot_id=previous, status="ready", ai_status="not_requested",
    )
    evidence = EvidenceReference(evidence_id="ev-1", source="source", snapshot_id="source-1", summary="fact", observed_at=NOW)
    advice = AdviceCard(
        advice_id=f"advice-{sequence}", snapshot_id=snapshot_id, asset="a_share", symbol="600000",
        horizon="intraday", observation_state="watching", action="simulated_plan" if planned else "observe",
        conclusion="wait", confidence=Decimal("0.6"), supporting_evidence=(evidence,), contrary_evidence=(),
        risks=("risk",), invalidation_conditions=("invalid",), quantitative_result={},
        risk_decision_id="risk-1" if planned else None, simulation_plan_id="plan-1" if planned else None,
        strategy_version="v1", created_at=NOW,
    )
    plans = ()
    if planned:
        plans = (SimulationPlan(
            plan_id="plan-1", advice_id=advice.advice_id, risk_decision_id="risk-1",
            compliance_snapshot_id="compliance-1", watch_price_low="10", watch_price_high="10.2",
            stop_loss="9.7", take_profit=("10.6",), tranches=("0.5",), max_position="0.5",
            invalidation_conditions=("invalid",), valid_from=NOW, valid_until=NOW + timedelta(hours=1),
            strategy_version="v1", risk_version="v1", compliance_version="v1",
        ),)
    return DecisionCycleAggregate(snapshot=snapshot, advice=(advice,), plans=plans)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE decision_cycles SET payload='{}' WHERE snapshot_id='cycle-1'",
        "DELETE FROM decision_cycles WHERE snapshot_id='cycle-1'",
        "UPDATE decision_advice SET payload='{}' WHERE advice_id='advice-1'",
        "DELETE FROM decision_advice WHERE advice_id='advice-1'",
        "UPDATE decision_plans SET payload='{}' WHERE plan_id='plan-1'",
        "DELETE FROM decision_plans WHERE plan_id='plan-1'",
    ],
)
def test_append_only_triggers_reject_update_and_delete(tmp_path: Path, statement: str) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    repository.append_cycle(aggregate(planned=True))
    with pytest.raises(sqlite3.IntegrityError):
        repository.connection.execute(statement)
    repository.close()


@pytest.mark.parametrize("collection", ["supporting_evidence", "contrary_evidence"])
def test_append_rejects_advice_evidence_after_cycle_window(
    tmp_path: Path, collection: str,
) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    item = aggregate()
    future = item.advice[0].supporting_evidence[0].model_copy(
        update={"observed_at": item.snapshot.window_end + timedelta(seconds=1)}
    )
    changes = {collection: (future,)}
    bad_advice = item.advice[0].model_copy(update=changes)
    with pytest.raises(DecisionIntegrityError, match="after snapshot window end"):
        repository.append_cycle(item.model_copy(update={"advice": (bad_advice,)}))
    assert repository.cycles() == []


def test_restart_recovery_idempotency_and_conflicting_id(tmp_path: Path) -> None:
    database = tmp_path / "decisions.sqlite3"
    repository = DecisionRepository(database)
    assert repository.append_cycle(aggregate()) is True
    assert repository.append_cycle(aggregate()) is False
    repository.close()
    restarted = DecisionRepository(database)
    assert restarted.latest(TRADE_DATE, "premarket") == aggregate()
    conflict = aggregate().model_copy(update={"snapshot": aggregate().snapshot.model_copy(update={"market_state": "weak"})})
    with pytest.raises(DecisionIntegrityError, match="collision"):
        restarted.append_cycle(conflict)
    restarted.close()


def test_sequence_and_previous_snapshot_are_enforced(tmp_path: Path) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    repository.append_cycle(aggregate())
    with pytest.raises(DecisionIntegrityError, match="sequence"):
        repository.append_cycle(aggregate(3, "cycle-1"))
    with pytest.raises(DecisionIntegrityError, match="previous snapshot"):
        repository.append_cycle(aggregate(2, "wrong"))
    repository.append_cycle(aggregate(2, "cycle-1"))
    repository.connection.execute("DROP TRIGGER reject_update_decision_cycles")
    repository.connection.execute("UPDATE decision_cycles SET previous_hash='bad' WHERE snapshot_id='cycle-2'")
    with pytest.raises(DecisionIntegrityError, match="chain"):
        repository.cycles()


def test_invalid_cross_references_roll_back_transaction(tmp_path: Path) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    item = aggregate(planned=True)
    bad_advice = item.advice[0].model_copy(update={"snapshot_id": "other"})
    with pytest.raises(DecisionIntegrityError, match="snapshot"):
        repository.append_cycle(item.model_copy(update={"advice": (bad_advice,)}))
    assert repository.cycles() == []


@pytest.mark.parametrize("corruption", ["payload", "missing_child", "reciprocal"])
def test_read_detects_corruption(tmp_path: Path, corruption: str) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    repository.append_cycle(aggregate(planned=True))
    repository.connection.execute("DROP TRIGGER reject_update_decision_cycles")
    repository.connection.execute("DROP TRIGGER reject_delete_decision_advice")
    repository.connection.execute("DROP TRIGGER reject_update_decision_advice")
    if corruption == "payload":
        repository.connection.execute("UPDATE decision_cycles SET payload='{}' WHERE snapshot_id='cycle-1'")
    elif corruption == "missing_child":
        repository.connection.execute("PRAGMA foreign_keys=OFF")
        repository.connection.execute("DELETE FROM decision_advice WHERE advice_id='advice-1'")
    else:
        repository.connection.execute("UPDATE decision_advice SET plan_id=NULL WHERE advice_id='advice-1'")
    with pytest.raises(DecisionIntegrityError):
        repository.cycles()


@pytest.mark.parametrize(
    ("table", "id_column", "stored_id", "trigger"),
    [
        ("decision_advice", "advice_id", "advice-tampered", "reject_update_decision_advice"),
        ("decision_plans", "plan_id", "plan-tampered", "reject_update_decision_plans"),
    ],
)
def test_read_detects_stored_child_id_corruption(
    tmp_path: Path, table: str, id_column: str, stored_id: str, trigger: str,
) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    repository.append_cycle(aggregate(planned=True))
    repository.connection.execute(f"DROP TRIGGER {trigger}")
    repository.connection.execute("PRAGMA foreign_keys=OFF")
    repository.connection.execute(f"UPDATE {table} SET {id_column}=?", (stored_id,))
    with pytest.raises(DecisionIntegrityError, match="stored .* link is corrupt"):
        repository.cycles()


def test_concurrent_reads_are_serialized_safely(tmp_path: Path) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    repository.append_cycle(aggregate())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: repository.cycles(), range(20)))
    assert all(result == [aggregate()] for result in results)
