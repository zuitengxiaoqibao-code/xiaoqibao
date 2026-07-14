import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from qibao_api.a_shares.diagnosis import AShareDiagnosis
from qibao_api.a_shares.models import CandidateBoard


class AShareResearchIntegrityError(RuntimeError):
    pass


class AShareResearchRepository:
    def __init__(self, database: str | Path) -> None:
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS candidate_snapshots (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          snapshot_id TEXT NOT NULL UNIQUE,
          as_of TEXT NOT NULL,
          input_snapshot_hash TEXT NOT NULL,
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
          canonical_hash TEXT NOT NULL,
          payload TEXT NOT NULL,
          recorded_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_a_share_diagnosis_symbol
        ON diagnosis_snapshots(symbol, sequence);
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

    def append_candidate_board(self, board: CandidateBoard) -> str:
        snapshot_id = f"a-share-candidates-{uuid4().hex}"
        stored, encoded, input_hash, canonical_hash = self._freeze(board, snapshot_id)
        with self.connection:
            self.connection.execute(
                """INSERT INTO candidate_snapshots(
                snapshot_id,as_of,input_snapshot_hash,canonical_hash,payload,recorded_at
                ) VALUES(?,?,?,?,?,?)""",
                (
                    snapshot_id, stored.as_of.isoformat(), input_hash, canonical_hash,
                    encoded, datetime.now(timezone.utc).isoformat(),
                ),
            )
        return snapshot_id

    def get_candidate_board(self, snapshot_id: str) -> CandidateBoard:
        row = self.connection.execute(
            "SELECT * FROM candidate_snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        return CandidateBoard.model_validate_json(self._verified_payload(row, snapshot_id))

    def append_diagnosis(self, diagnosis: AShareDiagnosis) -> str:
        snapshot_id = f"a-share-diagnosis-{uuid4().hex}"
        stored, encoded, input_hash, canonical_hash = self._freeze(diagnosis, snapshot_id)
        with self.connection:
            self.connection.execute(
                """INSERT INTO diagnosis_snapshots(
                snapshot_id,symbol,as_of,input_snapshot_hash,canonical_hash,payload,recorded_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    snapshot_id, stored.symbol, stored.as_of.isoformat(), input_hash,
                    canonical_hash, encoded, datetime.now(timezone.utc).isoformat(),
                ),
            )
        return snapshot_id

    def get_diagnosis(self, snapshot_id: str) -> AShareDiagnosis:
        row = self.connection.execute(
            "SELECT * FROM diagnosis_snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        return AShareDiagnosis.model_validate_json(self._verified_payload(row, snapshot_id))

    def verify_all(self) -> int:
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

    @staticmethod
    def _freeze(model: BaseModel, snapshot_id: str):
        if getattr(model, "snapshot_id", None) is not None:
            raise ValueError("cannot append an already frozen snapshot")
        base_payload = model.model_dump(
            mode="json", exclude={"snapshot_id", "input_snapshot_hash"}
        )
        base_encoded = json.dumps(
            base_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        input_hash = hashlib.sha256(base_encoded.encode("utf-8")).hexdigest()
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
        return stored, encoded, input_hash, canonical_hash

    @staticmethod
    def _verified_payload(row, snapshot_id: str) -> str:
        if row is None:
            raise KeyError(snapshot_id)
        computed = hashlib.sha256(row["payload"].encode("utf-8")).hexdigest()
        if not hmac.compare_digest(computed, row["canonical_hash"]):
            raise AShareResearchIntegrityError(
                f"A-share research snapshot {snapshot_id} failed integrity check"
            )
        payload = json.loads(row["payload"])
        if not hmac.compare_digest(payload["input_snapshot_hash"], row["input_snapshot_hash"]):
            raise AShareResearchIntegrityError(
                f"A-share research snapshot {snapshot_id} input hash differs"
            )
        return row["payload"]

    def close(self) -> None:
        self.connection.close()
