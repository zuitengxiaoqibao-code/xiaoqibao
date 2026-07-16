import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import AuditFinding
from qibao_api.dongchang.schema import SCHEMA
from qibao_api.dongchang.models import AuditInput, Snapshot


@dataclass(frozen=True)
class StoredSnapshot:
    snapshot: Snapshot
    content_hash: str


class AuditFindingRepository:
    def __init__(self, database: str | Path) -> None:
        self._lock = RLock()
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def append_audit(
        self, audit_input: AuditInput, findings: tuple[AuditFinding, ...]
    ) -> None:
        snapshot_ids = {audit_input.recommendation.snapshot_id, audit_input.outcome.snapshot_id}
        if any(
            finding.asset != audit_input.asset
            or set(finding.input_snapshot_ids) != snapshot_ids
            for finding in findings
        ):
            raise ValueError("findings must match current audit snapshots and asset")
        try:
            with self._lock, self.connection:
                for snapshot in (audit_input.recommendation, audit_input.outcome):
                    self.connection.execute(
                        """INSERT INTO audit_snapshots
                           (snapshot_id, asset, symbol, conclusion, evidence_link,
                            captured_at, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            snapshot.snapshot_id,
                            snapshot.asset.value,
                            snapshot.symbol,
                            snapshot.conclusion,
                            snapshot.evidence_link,
                            snapshot.captured_at.isoformat(),
                            snapshot.canonical_content_hash(),
                        ),
                    )
                for finding in findings:
                    self._append_finding(finding)
                    self.connection.executemany(
                        """INSERT INTO audit_finding_snapshots
                           (finding_id, snapshot_id, position) VALUES (?, ?, ?)""",
                        [
                            (finding.finding_id, snapshot_id, position)
                            for position, snapshot_id in enumerate(finding.input_snapshot_ids)
                        ],
                    )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"audit run {audit_input.audit_run_id!r} already exists") from error

    def _append_finding(self, finding: AuditFinding) -> None:
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
        self.connection.execute(
            """INSERT INTO audit_findings
               (finding_id, asset, finding_type, severity, evidence_json,
                input_snapshot_ids_json, owner_department, resolution_state, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )

    def get_snapshot(self, snapshot_id: str) -> StoredSnapshot:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM audit_snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        return StoredSnapshot(
            snapshot=Snapshot(
                snapshot_id=row["snapshot_id"],
                asset=row["asset"],
                symbol=row["symbol"],
                conclusion=row["conclusion"],
                evidence_link=row["evidence_link"],
                captured_at=row["captured_at"],
            ),
            content_hash=row["content_hash"],
        )

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
