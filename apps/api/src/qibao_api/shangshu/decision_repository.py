import hashlib
import hmac
import json
import sqlite3
import threading
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from qibao_api.contracts.decision import (
    AdviceCard,
    DecisionCycleAggregate,
    DecisionCycleSnapshot,
    DecisionPhase,
)


class DecisionIntegrityError(RuntimeError):
    pass


def _payload(model: DecisionCycleSnapshot | AdviceCard) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
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
          canonical_hash TEXT NOT NULL, advice_count INTEGER NOT NULL,
          payload TEXT NOT NULL, UNIQUE(trading_date, phase, sequence)
        );
        CREATE TABLE IF NOT EXISTS decision_advice (
          advice_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL,
          canonical_hash TEXT NOT NULL, payload TEXT NOT NULL,
          FOREIGN KEY(snapshot_id) REFERENCES decision_cycles(snapshot_id)
        );
        CREATE TRIGGER IF NOT EXISTS reject_update_decision_cycles BEFORE UPDATE ON decision_cycles
        BEGIN SELECT RAISE(ABORT, 'append-only decision cycles'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_decision_cycles BEFORE DELETE ON decision_cycles
        BEGIN SELECT RAISE(ABORT, 'append-only decision cycles'); END;
        CREATE TRIGGER IF NOT EXISTS reject_update_decision_advice BEFORE UPDATE ON decision_advice
        BEGIN SELECT RAISE(ABORT, 'append-only decision advice'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_decision_advice BEFORE DELETE ON decision_advice
        BEGIN SELECT RAISE(ABORT, 'append-only decision advice'); END;
        """)
        self._cycle_columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(decision_cycles)")
        }
        self._advice_columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(decision_advice)")
        }

    @staticmethod
    def _validate_references(aggregate: DecisionCycleAggregate) -> None:
        snapshot_id = aggregate.snapshot.snapshot_id
        advice_ids = {item.advice_id for item in aggregate.advice}
        if len(advice_ids) != len(aggregate.advice):
            raise DecisionIntegrityError("duplicate advice id")
        if any(item.snapshot_id != snapshot_id for item in aggregate.advice):
            raise DecisionIntegrityError("advice references a different snapshot")
        for advice in aggregate.advice:
            evidence = advice.supporting_evidence + advice.contrary_evidence
            if any(item.observed_at > aggregate.snapshot.window_end for item in evidence):
                raise DecisionIntegrityError("advice evidence is after snapshot window end")

    def append_cycle(self, aggregate: DecisionCycleAggregate) -> bool:
        self._validate_references(aggregate)
        snapshot = aggregate.snapshot
        snapshot_payload = _payload(snapshot)
        canonical_hash = _hash(snapshot_payload)
        with self._lock:
            existing = self.connection.execute(
                "SELECT canonical_hash FROM decision_cycles WHERE snapshot_id=?",
                (snapshot.snapshot_id,),
            ).fetchone()
            if existing is not None:
                if not hmac.compare_digest(existing["canonical_hash"], canonical_hash):
                    raise DecisionIntegrityError(f"snapshot id collision: {snapshot.snapshot_id}")
                if self._cycles(snapshot_id=snapshot.snapshot_id) != [aggregate]:
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
            columns = [
                "snapshot_id", "trading_date", "phase", "sequence", "previous_snapshot_id",
                "previous_hash", "canonical_hash", "advice_count",
            ]
            values = [
                snapshot.snapshot_id, snapshot.trading_date.isoformat(), snapshot.phase,
                snapshot.sequence, snapshot.previous_snapshot_id,
                None if tail is None else tail["canonical_hash"], canonical_hash,
                len(aggregate.advice),
            ]
            if "plan_count" in self._cycle_columns:
                columns.append("plan_count")
                values.append(0)
            columns.append("payload")
            values.append(snapshot_payload)
            try:
                with self.connection:
                    placeholders = ",".join("?" for _ in columns)
                    self.connection.execute(
                        f"INSERT INTO decision_cycles({','.join(columns)}) VALUES({placeholders})",
                        values,
                    )
                    for advice in aggregate.advice:
                        payload = _payload(advice)
                        advice_columns = ["advice_id", "snapshot_id"]
                        advice_values = [advice.advice_id, snapshot.snapshot_id]
                        if "plan_id" in self._advice_columns:
                            advice_columns.append("plan_id")
                            advice_values.append(None)
                        advice_columns.extend(("canonical_hash", "payload"))
                        advice_values.extend((_hash(payload), payload))
                        marks = ",".join("?" for _ in advice_columns)
                        self.connection.execute(
                            f"INSERT INTO decision_advice({','.join(advice_columns)}) VALUES({marks})",
                            advice_values,
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
                key = (row["trading_date"], row["phase"])
                prior = prior_by_chain.get(key)
                if snapshot_id is None:
                    if row["sequence"] != (1 if prior is None else int(prior["sequence"]) + 1):
                        raise DecisionIntegrityError("decision cycle chain is broken")
                    if row["previous_hash"] != (None if prior is None else prior["canonical_hash"]):
                        raise DecisionIntegrityError("decision cycle chain is broken")
                advice_rows = self.connection.execute(
                    "SELECT * FROM decision_advice WHERE snapshot_id=? ORDER BY advice_id",
                    (row["snapshot_id"],),
                ).fetchall()
                if len(advice_rows) != row["advice_count"]:
                    raise DecisionIntegrityError("decision aggregate has missing children")
                advice = tuple(self._validated_child(item) for item in advice_rows)
                for stored, model in zip(advice_rows, advice, strict=True):
                    if (stored["advice_id"] != model.advice_id
                            or stored["snapshot_id"] != snapshot.snapshot_id):
                        raise DecisionIntegrityError("stored advice link is corrupt")
                aggregate = DecisionCycleAggregate(snapshot=snapshot, advice=advice)
                self._validate_references(aggregate)
                results.append(aggregate)
                prior_by_chain[key] = row
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise DecisionIntegrityError("decision payload failed model validation") from exc
        return results

    @staticmethod
    def _validated_child(row: sqlite3.Row) -> AdviceCard:
        if not hmac.compare_digest(_hash(row["payload"]), row["canonical_hash"]):
            raise DecisionIntegrityError("decision child payload hash mismatch")
        return AdviceCard.model_validate_json(row["payload"])

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
