import hashlib
import hmac
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from qibao_api.a_shares.diagnosis import AShareDiagnosis
from qibao_api.a_shares.models import CandidateBoard


class AShareResearchStoreError(RuntimeError):
    pass


class AShareResearchIntegrityError(AShareResearchStoreError):
    pass


class AShareResearchRepository:
    def __init__(self, database: str | Path) -> None:
        self._lock = threading.RLock()
        try:
            self.connection = sqlite3.connect(database, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            self._initialize()
        except sqlite3.DatabaseError as error:
            raise AShareResearchStoreError("A-share research database cannot open") from error

    def _initialize(self) -> None:
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS candidate_snapshots (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          snapshot_id TEXT NOT NULL UNIQUE,
          as_of TEXT NOT NULL,
          input_snapshot_hash TEXT NOT NULL,
          input_payload TEXT NOT NULL,
          canonical_hash TEXT NOT NULL,
          payload TEXT NOT NULL,
          recorded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS diagnosis_snapshots (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          snapshot_id TEXT NOT NULL UNIQUE,
          symbol TEXT NOT NULL,
          as_of TEXT NOT NULL,
          input_snapshot_hash TEXT NOT NULL,
          input_payload TEXT NOT NULL,
          canonical_hash TEXT NOT NULL,
          payload TEXT NOT NULL,
          recorded_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_a_share_diagnosis_symbol
        ON diagnosis_snapshots(symbol, sequence);
        """)
        self._migrate_input_payload("candidate_snapshots", "reject_update_candidate_snapshots")
        self._migrate_input_payload("diagnosis_snapshots", "reject_update_diagnosis_snapshots")
        self.connection.executescript("""
        CREATE TRIGGER IF NOT EXISTS reject_update_candidate_snapshots
        BEFORE UPDATE ON candidate_snapshots
        BEGIN SELECT RAISE(ABORT, 'append-only candidate snapshots'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_candidate_snapshots
        BEFORE DELETE ON candidate_snapshots
        BEGIN SELECT RAISE(ABORT, 'append-only candidate snapshots'); END;
        CREATE TRIGGER IF NOT EXISTS reject_update_diagnosis_snapshots
        BEFORE UPDATE ON diagnosis_snapshots
        BEGIN SELECT RAISE(ABORT, 'append-only diagnosis snapshots'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_diagnosis_snapshots
        BEFORE DELETE ON diagnosis_snapshots
        BEGIN SELECT RAISE(ABORT, 'append-only diagnosis snapshots'); END;
        """)

    def _migrate_input_payload(self, table: str, update_trigger: str) -> None:
        columns = {
            row[1] for row in self.connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if "input_payload" in columns:
            return
        self.connection.execute(f"DROP TRIGGER IF EXISTS {update_trigger}")
        self.connection.execute(f"ALTER TABLE {table} ADD COLUMN input_payload TEXT")
        self.connection.execute(f"UPDATE {table} SET input_payload=payload")
        self.connection.commit()

    def append_candidate_board(
        self, board: CandidateBoard, input_payload: dict | None = None
    ) -> str:
        snapshot_id = f"a-share-candidates-{uuid4().hex}"
        stored, encoded, input_encoded, input_hash, canonical_hash = self._freeze(
            board, snapshot_id, input_payload
        )
        try:
            with self._lock, self.connection:
                self.connection.execute(
                    """INSERT INTO candidate_snapshots(
                    snapshot_id,as_of,input_snapshot_hash,input_payload,
                    canonical_hash,payload,recorded_at
                    ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        snapshot_id, stored.as_of.isoformat(), input_hash, input_encoded,
                        canonical_hash, encoded, datetime.now(timezone.utc).isoformat(),
                    ),
                )
        except sqlite3.DatabaseError as error:
            raise AShareResearchStoreError("candidate snapshot append failed") from error
        return snapshot_id

    def get_candidate_board(self, snapshot_id: str) -> CandidateBoard:
        try:
            with self._lock:
                row = self.connection.execute(
                    "SELECT * FROM candidate_snapshots WHERE snapshot_id=?", (snapshot_id,)
                ).fetchone()
                payload = self._verified_payload(row, snapshot_id)
            return CandidateBoard.model_validate_json(payload)
        except AShareResearchIntegrityError:
            raise
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, ValidationError) as error:
            raise AShareResearchStoreError("candidate snapshot read failed") from error

    def append_diagnosis(
        self, diagnosis: AShareDiagnosis, input_payload: dict | None = None
    ) -> str:
        snapshot_id = f"a-share-diagnosis-{uuid4().hex}"
        stored, encoded, input_encoded, input_hash, canonical_hash = self._freeze(
            diagnosis, snapshot_id, input_payload
        )
        try:
            with self._lock, self.connection:
                self.connection.execute(
                    """INSERT INTO diagnosis_snapshots(
                    snapshot_id,symbol,as_of,input_snapshot_hash,input_payload,
                    canonical_hash,payload,recorded_at
                    ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        snapshot_id, stored.symbol, stored.as_of.isoformat(), input_hash,
                        input_encoded, canonical_hash, encoded,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        except sqlite3.DatabaseError as error:
            raise AShareResearchStoreError("diagnosis snapshot append failed") from error
        return snapshot_id

    def get_diagnosis(self, snapshot_id: str) -> AShareDiagnosis:
        try:
            with self._lock:
                row = self.connection.execute(
                    "SELECT * FROM diagnosis_snapshots WHERE snapshot_id=?", (snapshot_id,)
                ).fetchone()
                payload = self._verified_payload(row, snapshot_id)
            return AShareDiagnosis.model_validate_json(payload)
        except AShareResearchIntegrityError:
            raise
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, ValidationError) as error:
            raise AShareResearchStoreError("diagnosis snapshot read failed") from error

    def verify_all(self) -> int:
        try:
            with self._lock:
                candidate_ids = [
                    row[0] for row in self.connection.execute(
                        "SELECT snapshot_id FROM candidate_snapshots ORDER BY sequence"
                    ).fetchall()
                ]
                diagnosis_ids = [
                    row[0] for row in self.connection.execute(
                        "SELECT snapshot_id FROM diagnosis_snapshots ORDER BY sequence"
                    ).fetchall()
                ]
            for snapshot_id in candidate_ids:
                self.get_candidate_board(snapshot_id)
            for snapshot_id in diagnosis_ids:
                self.get_diagnosis(snapshot_id)
            return len(candidate_ids) + len(diagnosis_ids)
        except AShareResearchStoreError:
            raise
        except sqlite3.DatabaseError as error:
            raise AShareResearchStoreError("research snapshot verification failed") from error

    @staticmethod
    def _freeze(model: BaseModel, snapshot_id: str, input_payload: dict | None):
        if getattr(model, "snapshot_id", None) is not None:
            raise ValueError("cannot append an already frozen snapshot")
        canonical_inputs = input_payload or model.model_dump(
            mode="json", exclude={"snapshot_id", "input_snapshot_hash"}
        )
        input_encoded = json.dumps(
            canonical_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        input_hash = hashlib.sha256(input_encoded.encode("utf-8")).hexdigest()
        stored = model.model_copy(update={
            "snapshot_id": snapshot_id, "input_snapshot_hash": input_hash
        })
        encoded = json.dumps(
            stored.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        canonical_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return stored, encoded, input_encoded, input_hash, canonical_hash

    @staticmethod
    def _verified_payload(row, snapshot_id: str) -> str:
        if row is None:
            raise KeyError(snapshot_id)
        computed = hashlib.sha256(row["payload"].encode("utf-8")).hexdigest()
        if not hmac.compare_digest(computed, row["canonical_hash"]):
            raise AShareResearchIntegrityError(
                f"A-share research snapshot {snapshot_id} failed integrity check"
            )
        computed_input = hashlib.sha256(row["input_payload"].encode("utf-8")).hexdigest()
        if not hmac.compare_digest(computed_input, row["input_snapshot_hash"]):
            raise AShareResearchIntegrityError(
                f"A-share research snapshot {snapshot_id} input payload failed integrity check"
            )
        payload = json.loads(row["payload"])
        if not hmac.compare_digest(payload["input_snapshot_hash"], computed_input):
            raise AShareResearchIntegrityError(
                f"A-share research snapshot {snapshot_id} input hash differs"
            )
        return row["payload"]

    def close(self) -> None:
        with self._lock:
            self.connection.close()
