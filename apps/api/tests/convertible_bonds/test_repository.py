from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError

from qibao_api.convertible_bonds.adapters import parse_eastmoney_clause_payload
from qibao_api.convertible_bonds.repository import ClauseRepository


def payload(price: str = "9.87") -> dict[str, str]:
    return {
        "bond_code": "113001",
        "linked_stock": "600000",
        "conversion_price": price,
        "maturity": "2030-07-14",
        "remaining_size": "12.345678",
        "conversion_start": "2026-01-01",
        "redemption_start": "2026-07-01",
        "put_back_start": "2029-01-01",
    }


def snapshot(price: str, hour: int):
    return parse_eastmoney_clause_payload(
        payload(price), fetched_at=datetime(2026, 7, 14, hour, tzinfo=timezone.utc)
    )


def test_duplicate_raw_snapshot_is_idempotent() -> None:
    repository = ClauseRepository(create_engine("sqlite+pysqlite:///:memory:"))
    repository.initialize()

    first_id = repository.append(snapshot("9.87", 1))
    duplicate_id = repository.append(snapshot("9.87", 2))

    assert duplicate_id == first_id
    assert len(repository.snapshots("113001")) == 1
    assert len(repository.events("113001")) == 1


def test_changed_conversion_price_appends_snapshot_and_normalized_event() -> None:
    repository = ClauseRepository(create_engine("sqlite+pysqlite:///:memory:"))
    repository.initialize()

    repository.append(snapshot("9.87", 1))
    repository.append(snapshot("9.66", 2))

    snapshots = repository.snapshots("113001")
    events = repository.events("113001")
    assert [item.contract.conversion_price for item in snapshots] == [
        Decimal("9.87"), Decimal("9.66")
    ]
    assert [item.event_type for item in events] == ["terms_observed", "conversion_price_changed"]
    assert events[1].previous_value == "9.87"
    assert events[1].current_value == "9.66"


def test_other_clause_change_does_not_claim_conversion_price_changed() -> None:
    repository = ClauseRepository(create_engine("sqlite+pysqlite:///:memory:"))
    repository.initialize()
    repository.append(snapshot("9.87", 1))
    changed = payload("9.87")
    changed["remaining_size"] = "11.000000"

    repository.append(parse_eastmoney_clause_payload(
        changed, fetched_at=datetime(2026, 7, 14, 2, tzinfo=timezone.utc)
    ))

    assert [event.event_type for event in repository.events("113001")] == [
        "terms_observed", "terms_observed"
    ]


def test_file_database_survives_repository_restart(tmp_path) -> None:
    database = tmp_path / "clauses.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    first = ClauseRepository(engine)
    first.initialize()
    first.append(snapshot("9.87", 1))
    engine.dispose()

    restarted = ClauseRepository(create_engine(f"sqlite+pysqlite:///{database}"))
    restarted.initialize()

    assert restarted.latest("113001") is not None
    assert restarted.latest("113001").contract.conversion_price == Decimal("9.87")


@pytest.mark.parametrize("statement", [
    "UPDATE bond_clause_snapshots SET source = 'changed'",
    "DELETE FROM bond_clause_events",
])
def test_database_rejects_mutation_of_clause_history(statement: str) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repository = ClauseRepository(engine)
    repository.initialize()
    repository.append(snapshot("9.87", 1))

    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(text(statement))
