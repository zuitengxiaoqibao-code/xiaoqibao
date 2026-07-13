import json
import sqlite3
from pathlib import Path
from threading import RLock

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import AuditFinding
from qibao_api.dongchang.schema import SCHEMA


class AuditFindingRepository:
    def __init__(self, database: str | Path) -> None:
        self._lock = RLock()
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def append(self, finding: AuditFinding) -> None:
        values = (
            finding.finding_id,
            finding.asset.value,
            finding.finding_type,
            finding.severity,
            json.dumps(finding.evidence, ensure_ascii=True),
            json.dumps(finding.input_snapshot_ids, ensure_ascii=True),
            finding.owner_department,
            finding.resolution_state,
            finding.detected_at.isoformat(),
        )
        try:
            with self._lock, self.connection:
                self.connection.execute(
                    """INSERT INTO audit_findings
                       (finding_id, asset, finding_type, severity, evidence_json,
                        input_snapshot_ids_json, owner_department, resolution_state, detected_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"audit finding {finding.finding_id!r} already exists") from error

    def list_findings(self, *, asset: AssetKind | str) -> list[AuditFinding]:
        asset = AssetKind(asset)
        with self._lock:
            rows = self.connection.execute(
                """SELECT * FROM audit_findings WHERE asset = ?
                   ORDER BY detected_at, sequence""",
                (asset.value,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AuditFinding:
        return AuditFinding(
            finding_id=row["finding_id"],
            asset=row["asset"],
            finding_type=row["finding_type"],
            severity=row["severity"],
            evidence=tuple(json.loads(row["evidence_json"])),
            input_snapshot_ids=tuple(json.loads(row["input_snapshot_ids_json"])),
            owner_department=row["owner_department"],
            resolution_state=row["resolution_state"],
            detected_at=row["detected_at"],
        )
