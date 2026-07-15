import hashlib
import hmac
import json
import sqlite3
import threading
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from qibao_api.contracts.decision import (
    AdviceCard, DecisionCycleAggregate, DecisionCycleSnapshot, DecisionPhase, SimulationPlan,
)


class DecisionIntegrityError(RuntimeError):
    pass


def _payload(model: DecisionCycleSnapshot | AdviceCard | SimulationPlan) -> str:
    return json.dumps(
        model.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DecisionRepository:
    def __init__(self, database: str | Path) -> None:
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS decision_cycles (
          snapshot_id TEXT PRIMARY KEY, trading_date TEXT NOT NULL, phase TEXT NOT NULL,
          sequence INTEGER NOT NULL, previous_snapshot_id TEXT, previous_hash TEXT,
          canonical_hash TEXT NOT NULL, advice_count INTEGER NOT NULL, plan_count INTEGER NOT NULL,
          payload TEXT NOT NULL, UNIQUE(trading_date, phase, sequence)
        );
        CREATE TABLE IF NOT EXISTS decision_advice (
          advice_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, plan_id TEXT,
          canonical_hash TEXT NOT NULL, payload TEXT NOT NULL,
          FOREIGN KEY(snapshot_id) REFERENCES decision_cycles(snapshot_id)
        );
        CREATE TABLE IF NOT EXISTS decision_plans (
          plan_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, advice_id TEXT NOT NULL,
          canonical_hash TEXT NOT NULL, payload TEXT NOT NULL,
          FOREIGN KEY(snapshot_id) REFERENCES decision_cycles(snapshot_id),
          FOREIGN KEY(advice_id) REFERENCES decision_advice(advice_id)
        );
        CREATE TRIGGER IF NOT EXISTS reject_update_decision_cycles BEFORE UPDATE ON decision_cycles
        BEGIN SELECT RAISE(ABORT, 'append-only decision cycles'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_decision_cycles BEFORE DELETE ON decision_cycles
        BEGIN SELECT RAISE(ABORT, 'append-only decision cycles'); END;
        CREATE TRIGGER IF NOT EXISTS reject_update_decision_advice BEFORE UPDATE ON decision_advice
        BEGIN SELECT RAISE(ABORT, 'append-only decision advice'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_decision_advice BEFORE DELETE ON decision_advice
        BEGIN SELECT RAISE(ABORT, 'append-only decision advice'); END;
        CREATE TRIGGER IF NOT EXISTS reject_update_decision_plans BEFORE UPDATE ON decision_plans
        BEGIN SELECT RAISE(ABORT, 'append-only decision plans'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_decision_plans BEFORE DELETE ON decision_plans
        BEGIN SELECT RAISE(ABORT, 'append-only decision plans'); END;
        """)

    @staticmethod
    def _validate_references(aggregate: DecisionCycleAggregate) -> None:
        snapshot_id = aggregate.snapshot.snapshot_id
        advice_by_id = {item.advice_id: item for item in aggregate.advice}
        plans_by_id = {item.plan_id: item for item in aggregate.plans}
        if len(advice_by_id) != len(aggregate.advice) or len(plans_by_id) != len(aggregate.plans):
            raise DecisionIntegrityError("duplicate advice or plan id")
        if any(item.snapshot_id != snapshot_id for item in aggregate.advice):
            raise DecisionIntegrityError("advice references a different snapshot")
        for advice in aggregate.advice:
            evidence = advice.supporting_evidence + advice.contrary_evidence
            if any(item.observed_at > aggregate.snapshot.window_end for item in evidence):
                raise DecisionIntegrityError("advice evidence is after snapshot window end")
        for plan in aggregate.plans:
            advice = advice_by_id.get(plan.advice_id)
            if advice is None:
                raise DecisionIntegrityError("plan references advice outside the aggregate")
            if advice.simulation_plan_id != plan.plan_id:
                raise DecisionIntegrityError("advice and plan references are not reciprocal")
            if advice.risk_decision_id != plan.risk_decision_id:
                raise DecisionIntegrityError("advice and plan risk references differ")
            gate = advice.simulation_gate
            if gate is None or gate.compliance_snapshot_id != plan.compliance_snapshot_id:
                raise DecisionIntegrityError("advice gate and plan compliance references differ")
        for advice in aggregate.advice:
            if advice.simulation_plan_id and advice.simulation_plan_id not in plans_by_id:
                raise DecisionIntegrityError("advice references a missing plan")

    def append_cycle(self, aggregate: DecisionCycleAggregate) -> bool:
        self._validate_references(aggregate)
        snapshot = aggregate.snapshot
        snapshot_payload = _payload(snapshot)
        canonical_hash = _hash(snapshot_payload)
        with self._lock:
            existing = self.connection.execute(
                "SELECT canonical_hash FROM decision_cycles WHERE snapshot_id=?", (snapshot.snapshot_id,)
            ).fetchone()
            if existing is not None:
                if not hmac.compare_digest(existing["canonical_hash"], canonical_hash):
                    raise DecisionIntegrityError(f"snapshot id collision: {snapshot.snapshot_id}")
                stored = self._cycles(snapshot_id=snapshot.snapshot_id)
                if stored != [aggregate]:
                    raise DecisionIntegrityError(f"snapshot id collision: {snapshot.snapshot_id}")
                return False
            tail = self.connection.execute(
                """SELECT snapshot_id,sequence,canonical_hash FROM decision_cycles
                WHERE trading_date=? AND phase=? ORDER BY sequence DESC LIMIT 1""",
                (snapshot.trading_date.isoformat(), snapshot.phase),
            ).fetchone()
            expected_sequence = 1 if tail is None else int(tail["sequence"]) + 1
            expected_previous = None if tail is None else tail["snapshot_id"]
            if snapshot.sequence != expected_sequence:
                raise DecisionIntegrityError("cycle sequence does not follow the stored chain")
            if snapshot.previous_snapshot_id != expected_previous:
                raise DecisionIntegrityError("previous snapshot does not match the stored chain")
            previous_hash = None if tail is None else tail["canonical_hash"]
            try:
                with self.connection:
                    self.connection.execute(
                        """INSERT INTO decision_cycles(snapshot_id,trading_date,phase,sequence,
                        previous_snapshot_id,previous_hash,canonical_hash,advice_count,plan_count,payload)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (snapshot.snapshot_id, snapshot.trading_date.isoformat(), snapshot.phase,
                         snapshot.sequence, snapshot.previous_snapshot_id, previous_hash, canonical_hash,
                         len(aggregate.advice), len(aggregate.plans), snapshot_payload),
                    )
                    for advice in aggregate.advice:
                        payload = _payload(advice)
                        self.connection.execute(
                            "INSERT INTO decision_advice VALUES(?,?,?,?,?)",
                            (advice.advice_id, snapshot.snapshot_id, advice.simulation_plan_id,
                             _hash(payload), payload),
                        )
                    for plan in aggregate.plans:
                        payload = _payload(plan)
                        self.connection.execute(
                            "INSERT INTO decision_plans VALUES(?,?,?,?,?)",
                            (plan.plan_id, snapshot.snapshot_id, plan.advice_id, _hash(payload), payload),
                        )
            except sqlite3.IntegrityError as exc:
                raise DecisionIntegrityError("decision aggregate transaction failed") from exc
        return True

    def _cycles(self, *, snapshot_id: str | None = None, trading_date: date | None = None,
                phase: DecisionPhase | None = None) -> list[DecisionCycleAggregate]:
        clauses: list[str] = []
        values: list[str] = []
        for column, value in (("snapshot_id", snapshot_id),
                              ("trading_date", trading_date.isoformat() if trading_date else None),
                              ("phase", phase)):
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"SELECT * FROM decision_cycles{where} ORDER BY trading_date,phase,sequence", values
        ).fetchall()
        results: list[DecisionCycleAggregate] = []
        prior_by_chain: dict[tuple[str, str], sqlite3.Row] = {}
        try:
            for row in rows:
                if not hmac.compare_digest(_hash(row["payload"]), row["canonical_hash"]):
                    raise DecisionIntegrityError("cycle payload hash mismatch")
                snapshot = DecisionCycleSnapshot.model_validate_json(row["payload"])
                if (snapshot.snapshot_id != row["snapshot_id"]
                        or snapshot.trading_date.isoformat() != row["trading_date"]
                        or snapshot.phase != row["phase"]
                        or snapshot.sequence != row["sequence"]
                        or snapshot.previous_snapshot_id != row["previous_snapshot_id"]):
                    raise DecisionIntegrityError("cycle metadata does not match its payload")
                key = (row["trading_date"], row["phase"])
                prior = prior_by_chain.get(key)
                if snapshot_id is None:
                    expected_sequence = 1 if prior is None else int(prior["sequence"]) + 1
                    expected_previous_hash = None if prior is None else prior["canonical_hash"]
                    expected_previous_id = None if prior is None else prior["snapshot_id"]
                    if (row["sequence"] != expected_sequence or row["previous_hash"] != expected_previous_hash
                            or row["previous_snapshot_id"] != expected_previous_id):
                        raise DecisionIntegrityError("decision cycle chain is broken")
                advice_rows = self.connection.execute(
                    "SELECT * FROM decision_advice WHERE snapshot_id=? ORDER BY advice_id",
                    (row["snapshot_id"],),
                ).fetchall()
                plan_rows = self.connection.execute(
                    "SELECT * FROM decision_plans WHERE snapshot_id=? ORDER BY plan_id",
                    (row["snapshot_id"],),
                ).fetchall()
                if len(advice_rows) != row["advice_count"] or len(plan_rows) != row["plan_count"]:
                    raise DecisionIntegrityError("decision aggregate has missing children")
                advice = tuple(self._validated_child(item, AdviceCard) for item in advice_rows)
                plans = tuple(self._validated_child(item, SimulationPlan) for item in plan_rows)
                for stored, model in zip(advice_rows, advice, strict=True):
                    if (stored["advice_id"] != model.advice_id
                            or stored["snapshot_id"] != snapshot.snapshot_id
                            or stored["plan_id"] != model.simulation_plan_id):
                        raise DecisionIntegrityError("stored reciprocal plan link is corrupt")
                for stored, model in zip(plan_rows, plans, strict=True):
                    if (stored["plan_id"] != model.plan_id
                            or stored["snapshot_id"] != snapshot.snapshot_id
                            or stored["advice_id"] != model.advice_id):
                        raise DecisionIntegrityError("stored plan link is corrupt")
                aggregate = DecisionCycleAggregate(snapshot=snapshot, advice=advice, plans=plans)
                self._validate_references(aggregate)
                results.append(aggregate)
                prior_by_chain[key] = row
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise DecisionIntegrityError("decision payload failed model validation") from exc
        return results

    @staticmethod
    def _validated_child(row: sqlite3.Row, model: type[AdviceCard] | type[SimulationPlan]):
        if not hmac.compare_digest(_hash(row["payload"]), row["canonical_hash"]):
            raise DecisionIntegrityError("decision child payload hash mismatch")
        return model.model_validate_json(row["payload"])

    def cycles(self, trading_date: date | None = None,
               phase: DecisionPhase | None = None) -> list[DecisionCycleAggregate]:
        with self._lock:
            return self._cycles(trading_date=trading_date, phase=phase)

    def latest(self, trading_date: date, phase: DecisionPhase) -> DecisionCycleAggregate | None:
        values = self.cycles(trading_date=trading_date, phase=phase)
        return values[-1] if values else None

    def close(self) -> None:
        with self._lock:
            self.connection.close()
