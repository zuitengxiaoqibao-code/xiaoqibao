import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class BondDiagnosisRepository:
    def __init__(self, database: str | Path) -> None:
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS bond_diagnoses (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT, diagnosis_id TEXT NOT NULL UNIQUE,
          bond_code TEXT NOT NULL, canonical_hash TEXT NOT NULL, payload TEXT NOT NULL,
          recorded_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_bond_diagnoses_code ON bond_diagnoses(bond_code, sequence);
        CREATE TRIGGER IF NOT EXISTS reject_update_bond_diagnoses BEFORE UPDATE ON bond_diagnoses
        BEGIN SELECT RAISE(ABORT, 'append-only bond diagnoses'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_bond_diagnoses BEFORE DELETE ON bond_diagnoses
        BEGIN SELECT RAISE(ABORT, 'append-only bond diagnoses'); END;
        """)

    def append(self, bond_code: str, payload: dict) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        canonical_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        diagnosis_id = f"bond-diagnosis-{uuid4().hex}"
        with self.connection:
            self.connection.execute(
                "INSERT INTO bond_diagnoses(diagnosis_id,bond_code,canonical_hash,payload,recorded_at) VALUES(?,?,?,?,?)",
                (diagnosis_id, bond_code, canonical_hash, encoded, datetime.now(timezone.utc).isoformat()),
            )
        return diagnosis_id

    def latest_by_bond(self) -> list[dict]:
        rows = self.connection.execute("""
          SELECT d.* FROM bond_diagnoses d JOIN (
            SELECT bond_code, MAX(sequence) sequence FROM bond_diagnoses GROUP BY bond_code
          ) latest ON d.sequence=latest.sequence ORDER BY d.bond_code
        """).fetchall()
        return [{"diagnosis_id": row["diagnosis_id"], "bond_code": row["bond_code"],
                 "canonical_hash": row["canonical_hash"], "payload": json.loads(row["payload"]),
                 "recorded_at": row["recorded_at"]} for row in rows]

    def close(self) -> None:
        self.connection.close()
