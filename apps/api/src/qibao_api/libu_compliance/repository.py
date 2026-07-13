import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from qibao_api.contracts.risk import ComplianceRecord
from qibao_api.contracts.market import AssetKind
from qibao_api.libu_compliance.schema import SCHEMA


@dataclass(frozen=True)
class FeatureAuthorization:
    feature: str
    asset: AssetKind
    allowed: bool
    blocked_sources: tuple[str, ...]
    blocked_reasons: tuple[str, ...]


@dataclass(frozen=True)
class FeatureSourceEvent:
    event_id: str
    feature: str
    asset: AssetKind
    source: str
    recorded_at: datetime


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

    def set_feature_sources(
        self, feature: str, asset: AssetKind | str, sources: tuple[str, ...]
    ) -> None:
        if not feature or not sources or any(not source for source in sources):
            raise ValueError("feature and sources must be non-empty")
        asset = AssetKind(asset)
        recorded_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self.connection:
            existing = {
                row["source"]
                for row in self.connection.execute(
                    """SELECT DISTINCT source FROM compliance_feature_source_events
                       WHERE feature = ? AND asset = ?""",
                    (feature, asset.value),
                ).fetchall()
            }
            self.connection.executemany(
                """INSERT INTO compliance_feature_source_events
                   (event_id, feature, asset, source, recorded_at) VALUES (?, ?, ?, ?, ?)""",
                [
                    (f"feature-source-{uuid4().hex}", feature, asset.value, source, recorded_at)
                    for source in dict.fromkeys(sources)
                    if source not in existing
                ],
            )

    def list_feature_source_history(
        self, feature: str, asset: AssetKind | str
    ) -> list[FeatureSourceEvent]:
        asset = AssetKind(asset)
        with self._lock:
            rows = self.connection.execute(
                """SELECT * FROM compliance_feature_source_events
                   WHERE feature = ? AND asset = ? ORDER BY sequence""",
                (feature, asset.value),
            ).fetchall()
        return [
            FeatureSourceEvent(
                event_id=row["event_id"],
                feature=row["feature"],
                asset=AssetKind(row["asset"]),
                source=row["source"],
                recorded_at=datetime.fromisoformat(row["recorded_at"]),
            )
            for row in rows
        ]

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

    def list_current_records(self, asset: AssetKind | str) -> list[ComplianceRecord]:
        asset = AssetKind(asset)
        with self._lock:
            sources = self.connection.execute(
                "SELECT DISTINCT source FROM compliance_records WHERE asset = ? ORDER BY source",
                (asset.value,),
            ).fetchall()
            return [self._latest_record(row["source"], asset) for row in sources]

    def get_current_record(self, source: str, asset: AssetKind | str) -> ComplianceRecord | None:
        with self._lock:
            return self._latest_record(source, AssetKind(asset))

    def check_feature_sources(
        self, feature: str, asset: AssetKind | str
    ) -> FeatureAuthorization:
        asset = AssetKind(asset)
        with self._lock:
            sources = self.connection.execute(
                """SELECT DISTINCT source FROM compliance_feature_source_events
                   WHERE feature = ? AND asset = ? ORDER BY source""",
                (feature, asset.value),
            ).fetchall()
            states = [
                (row["source"], self._latest_record(row["source"], asset)) for row in sources
            ]
        if not sources:
            return FeatureAuthorization(
                feature=feature,
                asset=asset,
                allowed=False,
                blocked_sources=(),
                blocked_reasons=("feature_sources_unregistered",),
            )
        blocked = tuple(source for source, record in states if self._block_reason(record) is not None)
        reasons = tuple(
            f"{source}:{reason}"
            for source, record in states
            if (reason := self._block_reason(record)) is not None
        )
        return FeatureAuthorization(
            feature=feature,
            asset=asset,
            allowed=not blocked,
            blocked_sources=blocked,
            blocked_reasons=reasons,
        )

    def require_feature_sources(self, feature: str, asset: AssetKind | str) -> None:
        decision = self.check_feature_sources(feature, asset)
        if not decision.allowed:
            raise SourceAuthorizationError(
                f"feature {feature!r} blocked by source authorization: "
                f"{', '.join(decision.blocked_reasons)}"
            )

    def _latest_record(self, source: str, asset: AssetKind) -> ComplianceRecord | None:
        row = self.connection.execute(
            """SELECT * FROM compliance_records WHERE source = ? AND asset = ?
               ORDER BY recorded_at DESC, sequence DESC LIMIT 1""",
            (source, asset.value),
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
