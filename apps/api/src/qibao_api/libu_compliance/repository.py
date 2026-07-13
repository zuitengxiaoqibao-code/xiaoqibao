import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from qibao_api.contracts.risk import ComplianceRecord
from qibao_api.libu_compliance.schema import SCHEMA


@dataclass(frozen=True)
class FeatureAuthorization:
    feature: str
    allowed: bool
    blocked_sources: tuple[str, ...]


class SourceAuthorizationError(PermissionError):
    pass


class ComplianceRepository:
    def __init__(self, database: str | Path) -> None:
        self._lock = RLock()
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def set_feature_sources(self, feature: str, sources: tuple[str, ...]) -> None:
        if not feature or not sources or any(not source for source in sources):
            raise ValueError("feature and sources must be non-empty")
        with self._lock, self.connection:
            self.connection.execute(
                "DELETE FROM compliance_feature_sources WHERE feature = ?", (feature,)
            )
            self.connection.executemany(
                "INSERT INTO compliance_feature_sources VALUES (?, ?)",
                [(feature, source) for source in dict.fromkeys(sources)],
            )

    def append_record(self, record: ComplianceRecord) -> None:
        values = (
            record.record_id,
            record.asset.value,
            record.source,
            record.permission_state,
            record.permission_reference,
            record.disclaimer_version,
            record.user_acknowledged_at.isoformat() if record.user_acknowledged_at else None,
            record.recorded_at.isoformat(),
        )
        try:
            with self._lock, self.connection:
                self.connection.execute(
                    """INSERT INTO compliance_records
                       (record_id, asset, source, permission_state, permission_reference,
                        disclaimer_version, user_acknowledged_at, recorded_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"compliance record {record.record_id!r} already exists") from error

    def list_source_history(self, source: str) -> list[ComplianceRecord]:
        with self._lock:
            rows = self.connection.execute(
                """SELECT * FROM compliance_records
                   WHERE source = ? ORDER BY recorded_at, sequence""",
                (source,),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def check_feature_sources(self, feature: str) -> FeatureAuthorization:
        with self._lock:
            sources = self.connection.execute(
                """SELECT source FROM compliance_feature_sources
                   WHERE feature = ? ORDER BY source""",
                (feature,),
            ).fetchall()
            states = [(row["source"], self._latest_record(row["source"])) for row in sources]
        blocked = tuple(source for source, record in states if self._block_reason(record) is not None)
        return FeatureAuthorization(feature=feature, allowed=not blocked, blocked_sources=blocked)

    def require_feature_sources(self, feature: str) -> None:
        with self._lock:
            sources = self.connection.execute(
                """SELECT source FROM compliance_feature_sources
                   WHERE feature = ? ORDER BY source""",
                (feature,),
            ).fetchall()
            blocked = [
                f"{row['source']}:{reason}"
                for row in sources
                if (reason := self._block_reason(self._latest_record(row["source"]))) is not None
            ]
        if blocked:
            raise SourceAuthorizationError(
                f"feature {feature!r} blocked by source authorization: {', '.join(blocked)}"
            )

    def _latest_record(self, source: str) -> ComplianceRecord | None:
        row = self.connection.execute(
            """SELECT * FROM compliance_records WHERE source = ?
               ORDER BY recorded_at DESC, sequence DESC LIMIT 1""",
            (source,),
        ).fetchone()
        return self._record_from_row(row) if row else None

    @staticmethod
    def _block_reason(record: ComplianceRecord | None) -> str | None:
        if record is None:
            return "missing"
        if record.permission_state != "authorized":
            return record.permission_state
        if record.user_acknowledged_at is None:
            return "disclaimer_unacknowledged"
        return None

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ComplianceRecord:
        return ComplianceRecord(
            record_id=row["record_id"],
            asset=row["asset"],
            source=row["source"],
            permission_state=row["permission_state"],
            permission_reference=row["permission_reference"],
            disclaimer_version=row["disclaimer_version"],
            user_acknowledged_at=row["user_acknowledged_at"],
            recorded_at=row["recorded_at"],
        )
