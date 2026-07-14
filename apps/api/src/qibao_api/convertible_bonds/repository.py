import hashlib
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
    UniqueConstraint("bond_code", "source", "content_hash", name="uq_bond_clause_content"),
)

clause_events = Table(
    "bond_clause_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("bond_code", String(6), nullable=False, index=True),
    Column("source", String(32), nullable=False, index=True),
    Column("snapshot_id", ForeignKey("bond_clause_snapshots.id"), nullable=False, unique=True),
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
    snapshot_id: int


class ClauseRepository:
    def __init__(self, engine) -> None:
        self.engine = engine

    def initialize(self) -> None:
        metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            for table_name in ("bond_clause_snapshots", "bond_clause_events"):
                for operation in ("UPDATE", "DELETE"):
                    trigger = f"reject_{operation.lower()}_{table_name}"
                    connection.execute(text(f"""
                        CREATE TRIGGER IF NOT EXISTS {trigger}
                        BEFORE {operation} ON {table_name}
                        BEGIN
                            SELECT RAISE(ABORT, 'append-only clause history');
                        END
                    """))

    def append(self, snapshot: BondClauseSnapshot) -> int:
        computed_hash = hashlib.sha256(snapshot.raw_payload).hexdigest()
        if snapshot.content_hash != computed_hash:
            raise ValueError("clause snapshot content hash does not match raw payload")

        observed_at = _utc_iso(snapshot.fetched_at)
        contract_payload = snapshot.contract.model_dump(mode="json")
        with self.engine.begin() as connection:
            previous = connection.execute(
                select(
                    clause_snapshots.c.fetched_at,
                    clause_snapshots.c.normalized_payload,
                )
                .where(
                    clause_snapshots.c.bond_code == snapshot.contract.bond_code,
                    clause_snapshots.c.source == snapshot.source,
                )
                .order_by(clause_snapshots.c.fetched_at.desc())
                .limit(1)
            ).mappings().one_or_none()

            result = connection.execute(
                sqlite_insert(clause_snapshots)
                .values(
                    bond_code=snapshot.contract.bond_code,
                    source=snapshot.source,
                    fetched_at=observed_at,
                    content_hash=computed_hash,
                    raw_payload=snapshot.raw_payload,
                    normalized_payload=contract_payload,
                )
                .on_conflict_do_nothing(
                    index_elements=["bond_code", "source", "content_hash"]
                )
            )
            snapshot_id = connection.execute(
                select(clause_snapshots.c.id).where(
                    clause_snapshots.c.bond_code == snapshot.contract.bond_code,
                    clause_snapshots.c.source == snapshot.source,
                    clause_snapshots.c.content_hash == computed_hash,
                )
            ).scalar_one()
            if result.rowcount == 0:
                return snapshot_id

            if previous is not None and previous["fetched_at"] >= observed_at:
                return snapshot_id

            previous_price = (
                Decimal(previous["normalized_payload"]["conversion_price"])
                if previous is not None
                else None
            )
            current_price = snapshot.contract.conversion_price
            event_type = (
                "conversion_price_changed"
                if previous_price is not None and previous_price != current_price
                else "terms_observed"
            )
            connection.execute(
                sqlite_insert(clause_events)
                .values(
                    bond_code=snapshot.contract.bond_code,
                    source=snapshot.source,
                    snapshot_id=snapshot_id,
                    event_type=event_type,
                    previous_value=_decimal_text(previous_price),
                    current_value=_decimal_text(current_price),
                    observed_at=observed_at,
                )
                .on_conflict_do_nothing(index_elements=["snapshot_id"])
            )
        return snapshot_id

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
        statement = statement.order_by(clause_snapshots.c.fetched_at.desc()).limit(1)
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return self._snapshot_from_row(row) if row else None

    def events(self, bond_code: str, *, source: str | None = None) -> list[ClauseEvent]:
        statement = select(clause_events).where(clause_events.c.bond_code == bond_code)
        if source is not None:
            statement = statement.where(clause_events.c.source == source)
        statement = statement.order_by(clause_events.c.observed_at)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            ClauseEvent(
                event_type=row["event_type"],
                previous_value=row["previous_value"],
                current_value=row["current_value"],
                observed_at=datetime.fromisoformat(row["observed_at"]),
                snapshot_id=row["snapshot_id"],
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
        )


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")
