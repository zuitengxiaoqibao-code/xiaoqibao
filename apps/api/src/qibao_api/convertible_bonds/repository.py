import hashlib
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    JSON,
    Column,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from qibao_api.contracts.convertible_bond import ConvertibleBondContract
from qibao_api.convertible_bonds.models import BondClauseSnapshot
from qibao_api.convertible_bonds.adapters import parse_eastmoney_clause_bundle

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()

metadata = MetaData()

clause_snapshots = Table(
    "bond_clause_snapshots",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("bond_code", String(6), nullable=False, index=True),
    Column("source", String(32), nullable=False),
    Column("fetched_at", String(64), nullable=False, index=True),
    Column("content_hash", String(64), nullable=False),
    Column("raw_payload", LargeBinary, nullable=False),
    Column("normalized_payload", JSON, nullable=False),
    Column("parser_version", String(64), nullable=False),
    UniqueConstraint(
        "bond_code",
        "source",
        "content_hash",
        "parser_version",
        name="uq_bond_clause_content_parser",
    ),
)

clause_events = Table(
    "bond_clause_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("bond_code", String(6), nullable=False, index=True),
    Column("source", String(32), nullable=False, index=True),
    Column("revision", Integer, nullable=False, index=True),
    Column("projection_kind", String(16), nullable=False),
    Column("snapshot_id", ForeignKey("bond_clause_snapshots.id"), nullable=False),
    Column("from_snapshot_id", Integer),
    Column("event_key", String(128), nullable=False, unique=True),
    Column("event_type", String(32), nullable=False),
    Column("previous_value", String(64)),
    Column("current_value", String(64), nullable=False),
    Column("observed_at", String(64), nullable=False),
)


class ClauseEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: Literal["terms_observed", "conversion_price_changed"]
    previous_value: Decimal | None
    current_value: Decimal
    observed_at: datetime


class EventRevision(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: str
    revision: int
    projection_kind: Literal["legacy", "canonical"]
    events: tuple[ClauseEvent, ...]


class ClauseRepository:
    def __init__(self, engine, *, verifiers=None) -> None:
        self.engine = engine
        self.verifiers = {
            ("eastmoney", "eastmoney-v2"): lambda raw, code, when: (
                parse_eastmoney_clause_bundle(raw, requested_bond_code=code, fetched_at=when)
            )
        }
        self.verifiers.update(verifiers or {})

    def initialize(self) -> None:
        lock = _database_lock(str(self.engine.url))
        with lock, self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            metadata.create_all(connection)
            migrated = self._migrate_legacy_schema(connection)
            if migrated:
                groups = connection.execute(
                    select(clause_snapshots.c.bond_code, clause_snapshots.c.source).distinct()
                ).all()
                for bond_code, source in groups:
                    self._project_event_revision(connection, bond_code, source)
            connection.exec_driver_sql("PRAGMA user_version = 6")
            for table_name in ("bond_clause_snapshots", "bond_clause_events"):
                for operation in ("UPDATE", "DELETE"):
                    trigger = f"reject_{operation.lower()}_{table_name}"
                    connection.execute(
                        text(f"""
                        CREATE TRIGGER IF NOT EXISTS {trigger}
                        BEFORE {operation} ON {table_name}
                        BEGIN
                            SELECT RAISE(ABORT, 'append-only clause history');
                        END
                    """)
                    )
            connection.commit()

    def close(self) -> None:
        self.engine.dispose()

    def _migrate_legacy_schema(self, connection) -> bool:
        for table_name in ("bond_clause_snapshots", "bond_clause_events"):
            for operation in ("update", "delete"):
                connection.exec_driver_sql(
                    f"DROP TRIGGER IF EXISTS reject_{operation}_{table_name}"
                )
        if connection.exec_driver_sql("PRAGMA user_version").scalar() >= 6:
            return False
        snapshot_columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(bond_clause_snapshots)")
        }
        event_columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(bond_clause_events)")
        }
        connection.exec_driver_sql("ALTER TABLE bond_clause_snapshots RENAME TO snapshots_v3")
        connection.exec_driver_sql("ALTER TABLE bond_clause_events RENAME TO events_v3")
        for index_name in (
            "ix_bond_clause_snapshots_bond_code",
            "ix_bond_clause_snapshots_fetched_at",
            "ix_bond_clause_events_bond_code",
            "ix_bond_clause_events_source",
            "ix_bond_clause_events_revision",
        ):
            connection.exec_driver_sql(f"DROP INDEX IF EXISTS {index_name}")
        metadata.create_all(connection)
        parser_expr = "parser_version" if "parser_version" in snapshot_columns else "'legacy-v1'"
        rows = connection.exec_driver_sql(
            f"SELECT id,bond_code,source,fetched_at,raw_payload,normalized_payload,{parser_expr} "
            "FROM snapshots_v3"
        ).all()
        for row in rows:
            raw = row[4] if isinstance(row[4], bytes) else str(row[4]).encode("utf-8")
            connection.exec_driver_sql(
                "INSERT INTO bond_clause_snapshots VALUES (?,?,?,?,?,?,?,?)",
                (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    hashlib.sha256(raw).hexdigest(),
                    raw,
                    row[5],
                    row[6],
                ),
            )
        source_expr = (
            "source"
            if "source" in event_columns
            else "(SELECT source FROM snapshots_v3 WHERE snapshots_v3.id=events_v3.snapshot_id)"
        )
        connection.exec_driver_sql(f"""
            INSERT INTO bond_clause_events
            (id,bond_code,source,revision,projection_kind,snapshot_id,from_snapshot_id,event_key,event_type,
             previous_value,current_value,observed_at)
            SELECT id,bond_code,{source_expr},1,'legacy',snapshot_id,NULL,'legacy:'||id,event_type,
                   previous_value,current_value,observed_at FROM events_v3
        """)
        connection.exec_driver_sql("DROP TABLE events_v3")
        connection.exec_driver_sql("DROP TABLE snapshots_v3")
        return True

    def append(self, snapshot: BondClauseSnapshot) -> int:
        computed_hash = hashlib.sha256(snapshot.raw_payload).hexdigest()
        if snapshot.content_hash != computed_hash:
            raise ValueError("clause snapshot content hash does not match raw payload")
        verifier = self.verifiers.get((snapshot.source, snapshot.parser_version))
        if verifier is None:
            raise ValueError("no verifier registered for source/parser version")
        reparsed = verifier(snapshot.raw_payload, snapshot.contract.bond_code, snapshot.fetched_at)
        if _contract_identity(reparsed.contract) != _contract_identity(snapshot.contract):
            raise ValueError("normalized contract does not match raw clause reports")

        observed_at = _utc_iso(snapshot.fetched_at)
        contract_payload = snapshot.contract.model_dump(mode="json")
        lock = _database_lock(str(self.engine.url))
        with lock, self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                snapshot_id = self._append_in_transaction(
                    connection, snapshot, computed_hash, observed_at, contract_payload
                )
                connection.commit()
                return snapshot_id
            except Exception:
                connection.rollback()
                raise

    def _append_in_transaction(
        self, connection, snapshot, computed_hash, observed_at, contract_payload
    ) -> int:
        result = connection.execute(
            sqlite_insert(clause_snapshots)
            .values(
                bond_code=snapshot.contract.bond_code,
                source=snapshot.source,
                fetched_at=observed_at,
                content_hash=computed_hash,
                raw_payload=snapshot.raw_payload,
                normalized_payload=contract_payload,
                parser_version=snapshot.parser_version,
            )
            .on_conflict_do_nothing(
                index_elements=["bond_code", "source", "content_hash", "parser_version"]
            )
        )
        snapshot_id = connection.execute(
            select(clause_snapshots.c.id).where(
                clause_snapshots.c.bond_code == snapshot.contract.bond_code,
                clause_snapshots.c.source == snapshot.source,
                clause_snapshots.c.content_hash == computed_hash,
                clause_snapshots.c.parser_version == snapshot.parser_version,
            )
        ).scalar_one()
        if result.rowcount:
            self._project_event_revision(connection, snapshot.contract.bond_code, snapshot.source)
        return snapshot_id

    def _project_event_revision(self, connection, bond_code: str, source: str) -> None:
        rows = (
            connection.execute(
                select(clause_snapshots)
                .where(
                    clause_snapshots.c.bond_code == bond_code,
                    clause_snapshots.c.source == source,
                )
                .order_by(clause_snapshots.c.fetched_at, clause_snapshots.c.id)
            )
            .mappings()
            .all()
        )
        revision = (
            connection.execute(
                select(clause_events.c.revision)
                .where(
                    clause_events.c.bond_code == bond_code,
                    clause_events.c.source == source,
                )
                .order_by(clause_events.c.revision.desc())
                .limit(1)
            ).scalar_one_or_none()
            or 0
        ) + 1
        for index, current in enumerate(rows):
            previous = rows[index - 1] if index else None
            previous_price = (
                Decimal(previous["normalized_payload"]["conversion_price"]) if previous else None
            )
            current_price = Decimal(current["normalized_payload"]["conversion_price"])
            changed = previous_price is not None and previous_price != current_price
            if previous is not None and not changed:
                continue
            event_key = (
                f"r{revision}:change:{previous['id']}:{current['id']}"
                if changed
                else f"r{revision}:observed:{current['id']}"
            )
            connection.execute(
                sqlite_insert(clause_events)
                .values(
                    bond_code=bond_code,
                    source=source,
                    revision=revision,
                    projection_kind="canonical",
                    snapshot_id=current["id"],
                    from_snapshot_id=previous["id"] if changed else None,
                    event_key=event_key,
                    event_type="conversion_price_changed" if changed else "terms_observed",
                    previous_value=_decimal_text(previous_price),
                    current_value=_decimal_text(current_price),
                    observed_at=current["fetched_at"],
                )
                .on_conflict_do_nothing(index_elements=["event_key"])
            )

    def snapshots(self, bond_code: str) -> list[BondClauseSnapshot]:
        statement = (
            select(clause_snapshots)
            .where(clause_snapshots.c.bond_code == bond_code)
            .order_by(clause_snapshots.c.fetched_at)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._snapshot_from_row(row) for row in rows]

    def latest(self, bond_code: str, *, source: str | None = None) -> BondClauseSnapshot | None:
        statement = select(clause_snapshots).where(clause_snapshots.c.bond_code == bond_code)
        if source is not None:
            statement = statement.where(clause_snapshots.c.source == source)
        statement = statement.order_by(
            clause_snapshots.c.fetched_at.desc(), clause_snapshots.c.id.desc()
        ).limit(1)
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return self._snapshot_from_row(row) if row else None

    def all_latest(self) -> list[BondClauseSnapshot]:
        with self.engine.connect() as connection:
            codes = connection.execute(
                select(clause_snapshots.c.bond_code).distinct().order_by(clause_snapshots.c.bond_code)
            ).scalars().all()
        return [item for code in codes if (item := self.latest(code)) is not None]

    def events(self, bond_code: str, *, source: str | None = None) -> list[ClauseEvent]:
        return self.list_events(bond_code, source=source)

    def list_events(self, bond_code: str, *, source: str | None = None) -> list[ClauseEvent]:
        if source is None:
            with self.engine.connect() as connection:
                sources = (
                    connection.execute(
                        select(clause_events.c.source)
                        .where(
                            clause_events.c.bond_code == bond_code,
                            clause_events.c.projection_kind == "canonical",
                        )
                        .distinct()
                    )
                    .scalars()
                    .all()
                )
            return [
                event
                for item_source in sorted(sources)
                for event in self.list_events(bond_code, source=item_source)
            ]
        statement = select(clause_events).where(
            clause_events.c.bond_code == bond_code,
            clause_events.c.source == source,
            clause_events.c.projection_kind == "canonical",
        )
        with self.engine.connect() as connection:
            revision = connection.execute(
                select(clause_events.c.revision)
                .where(*statement._where_criteria)
                .order_by(clause_events.c.revision.desc())
                .limit(1)
            ).scalar_one_or_none()
        if revision is None:
            return []
        statement = statement.where(clause_events.c.revision == revision)
        statement = statement.order_by(clause_events.c.observed_at, clause_events.c.id)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            ClauseEvent(
                event_type=row["event_type"],
                previous_value=row["previous_value"],
                current_value=row["current_value"],
                observed_at=datetime.fromisoformat(row["observed_at"]),
            )
            for row in rows
        ]

    def list_event_revisions(
        self, bond_code: str, *, source: str | None = None
    ) -> list[EventRevision]:
        statement = select(
            clause_events.c.source,
            clause_events.c.revision,
            clause_events.c.projection_kind,
        ).where(clause_events.c.bond_code == bond_code)
        if source is not None:
            statement = statement.where(clause_events.c.source == source)
        with self.engine.connect() as connection:
            revisions = connection.execute(
                statement.distinct().order_by(
                    clause_events.c.source,
                    clause_events.c.revision,
                    clause_events.c.projection_kind,
                )
            ).all()
        return [
            EventRevision(
                source=item_source,
                revision=revision,
                projection_kind=kind,
                events=tuple(self._events_for_revision(bond_code, item_source, revision, kind)),
            )
            for item_source, revision, kind in revisions
        ]

    def _events_for_revision(self, bond_code, source, revision, kind):
        statement = select(clause_events).where(
            clause_events.c.bond_code == bond_code,
            clause_events.c.revision == revision,
            clause_events.c.projection_kind == kind,
        )
        if source is not None:
            statement = statement.where(clause_events.c.source == source)
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    statement.order_by(clause_events.c.observed_at, clause_events.c.id)
                )
                .mappings()
                .all()
            )
        return [
            ClauseEvent(
                event_type=row["event_type"],
                previous_value=row["previous_value"],
                current_value=row["current_value"],
                observed_at=datetime.fromisoformat(row["observed_at"]),
            )
            for row in rows
        ]

    @staticmethod
    def _snapshot_from_row(row) -> BondClauseSnapshot:
        return BondClauseSnapshot(
            contract=ConvertibleBondContract.model_validate(row["normalized_payload"]),
            raw_payload=bytes(row["raw_payload"]),
            content_hash=row["content_hash"],
            source=row["source"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            parser_version=row["parser_version"],
        )


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


BondClauseRepository = ClauseRepository


def _database_lock(database_url: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(database_url, threading.RLock())


def _contract_identity(contract: ConvertibleBondContract) -> tuple:
    return (
        contract.bond_code,
        contract.linked_stock,
        contract.conversion_price,
        contract.maturity,
        contract.remaining_size,
        contract.clause_dates,
    )
