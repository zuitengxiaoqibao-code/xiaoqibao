import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError

from qibao_api.convertible_bonds.adapters import parse_eastmoney_clause_payload
from qibao_api.convertible_bonds.repository import ClauseRepository
from tests.convertible_bonds.test_adapters import eastmoney_body


def snapshot(price: str, hour: int, *, source: str = "eastmoney"):
    item = parse_eastmoney_clause_payload(
        eastmoney_body(price=price),
        requested_bond_code="113001",
        fetched_at=datetime(2026, 7, 14, hour, tzinfo=timezone.utc),
    )
    return item.model_copy(update={"source": source})


def test_raw_snapshot_bytes_are_immutable_and_hash_is_revalidated() -> None:
    repository = ClauseRepository(create_engine("sqlite+pysqlite:///:memory:"))
    repository.initialize()
    item = snapshot("9.87", 1)

    assert isinstance(item.raw_payload, bytes)
    assert item.content_hash == hashlib.sha256(item.raw_payload).hexdigest()
    tampered = item.model_copy(update={"content_hash": "0" * 64})
    with pytest.raises(ValueError, match="content hash"):
        repository.append(tampered)


def test_duplicate_raw_snapshot_is_idempotent() -> None:
    repository = ClauseRepository(create_engine("sqlite+pysqlite:///:memory:"))
    repository.initialize()

    first_id = repository.append(snapshot("9.87", 1))
    duplicate_id = repository.append(snapshot("9.87", 2))

    assert duplicate_id == first_id
    assert len(repository.snapshots("113001")) == 1
    assert len(repository.events("113001", source="eastmoney")) == 1


def test_concurrent_repositories_append_duplicate_once(tmp_path) -> None:
    database = tmp_path / "clauses.sqlite3"
    engine_a = create_engine(f"sqlite+pysqlite:///{database}")
    engine_b = create_engine(f"sqlite+pysqlite:///{database}")
    first = ClauseRepository(engine_a)
    second = ClauseRepository(engine_b)
    first.initialize()
    item = snapshot("9.87", 1)

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda repo: repo.append(item), [first, second] * 8))

    assert len(set(ids)) == 1
    assert len(first.snapshots("113001")) == 1
    assert len(first.events("113001", source="eastmoney")) == 1


def test_changed_conversion_price_appends_normalized_event() -> None:
    repository = ClauseRepository(create_engine("sqlite+pysqlite:///:memory:"))
    repository.initialize()
    repository.append(snapshot("9.87", 1))
    repository.append(snapshot("9.66", 2))

    events = repository.events("113001", source="eastmoney")
    assert [event.event_type for event in events] == [
        "terms_observed", "conversion_price_changed"
    ]
    assert events[1].previous_value == Decimal("9.87")
    assert events[1].current_value == Decimal("9.66")


def test_decimal_scale_difference_does_not_create_price_change() -> None:
    repository = ClauseRepository(create_engine("sqlite+pysqlite:///:memory:"))
    repository.initialize()
    repository.append(snapshot("9.87", 1))
    repository.append(snapshot("9.870", 2))

    assert [event.event_type for event in repository.events(
        "113001", source="eastmoney"
    )] == ["terms_observed", "terms_observed"]


def test_latest_uses_fetched_time_and_out_of_order_snapshot_is_archive_only() -> None:
    repository = ClauseRepository(create_engine("sqlite+pysqlite:///:memory:"))
    repository.initialize()
    repository.append(snapshot("9.66", 2))
    repository.append(snapshot("9.87", 1))

    assert repository.latest("113001", source="eastmoney").contract.conversion_price == Decimal(
        "9.66"
    )
    assert len(repository.snapshots("113001")) == 2
    assert len(repository.events("113001", source="eastmoney")) == 1


def test_event_chains_are_isolated_by_source() -> None:
    repository = ClauseRepository(create_engine("sqlite+pysqlite:///:memory:"))
    repository.initialize()
    repository.append(snapshot("9.87", 1, source="eastmoney"))
    repository.append(snapshot("8.50", 1, source="licensed-feed"))
    repository.append(snapshot("8.25", 2, source="licensed-feed"))

    assert len(repository.events("113001", source="eastmoney")) == 1
    licensed = repository.events("113001", source="licensed-feed")
    assert [event.event_type for event in licensed] == [
        "terms_observed", "conversion_price_changed"
    ]
    assert repository.latest(
        "113001", source="licensed-feed"
    ).contract.conversion_price == Decimal("8.25")


def test_file_database_survives_repository_restart(tmp_path) -> None:
    database = tmp_path / "clauses.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    first = ClauseRepository(engine)
    first.initialize()
    first.append(snapshot("9.87", 1))
    engine.dispose()

    restarted = ClauseRepository(create_engine(f"sqlite+pysqlite:///{database}"))
    restarted.initialize()
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
