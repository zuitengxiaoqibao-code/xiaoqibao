import hashlib
import json
import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from qibao_api.a_shares.models import CandidateBoard, CandidateEntry, FactorSnapshot
from qibao_api.a_shares.diagnosis import AShareDiagnosis, DiagnosisSection
from qibao_api.a_shares.repository import (
    AShareResearchIntegrityError,
    AShareResearchRepository,
)


AS_OF = date(2026, 7, 14)


def board() -> CandidateBoard:
    factor = FactorSnapshot(
        symbol="600000", as_of=AS_OF, close=Decimal("10"),
        return_5d=Decimal("0.05"), return_20d=Decimal("0.10"),
        distance_ma20=Decimal("0.03"), volume_ratio_5_20=Decimal("1.2"),
        volatility_20d=Decimal("0.02"), drawdown_60d=Decimal("-0.04"),
        liquidity_amount_20d=Decimal("50000000"), source="mootdx",
    )
    entry = CandidateEntry(
        symbol="600000", horizon="short_term", score=Decimal("50"),
        score_breakdown={"momentum": Decimal("50")}, factor_snapshot=factor,
    )
    return CandidateBoard(as_of=AS_OF, short_term=[entry], swing=[])


def diagnosis() -> AShareDiagnosis:
    sections = {
        name: DiagnosisSection(
            status="ready", observed_at=AS_OF, source="fixture",
            metrics={}, explanation="固定测试分区",
        )
        for name in (
            "market", "price_volume", "trend", "valuation", "fundamentals",
            "funds", "events", "industry", "risk",
        )
    }
    return AShareDiagnosis(
        symbol="600000", as_of=AS_OF, action="observe", overall_status="ready",
        sections=sections,
    )


def test_candidate_snapshot_is_append_only_hash_verified_and_reopenable(tmp_path) -> None:
    database = tmp_path / "a-share-research.sqlite3"
    repository = AShareResearchRepository(database)

    snapshot_id = repository.append_candidate_board(board())
    stored = repository.get_candidate_board(snapshot_id)

    assert stored.snapshot_id == snapshot_id
    assert stored.short_term[0].symbol == "600000"
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        repository.connection.execute("UPDATE candidate_snapshots SET payload='{}'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        repository.connection.execute("DELETE FROM candidate_snapshots")
    repository.close()

    reopened = AShareResearchRepository(database)
    assert reopened.get_candidate_board(snapshot_id) == stored
    reopened.close()


def test_repository_detects_candidate_payload_tampering(tmp_path) -> None:
    repository = AShareResearchRepository(tmp_path / "tampered.sqlite3")
    snapshot_id = repository.append_candidate_board(board())
    repository.connection.execute("DROP TRIGGER reject_update_candidate_snapshots")
    repository.connection.execute(
        "UPDATE candidate_snapshots SET payload='{}' WHERE snapshot_id=?",
        (snapshot_id,),
    )
    repository.connection.commit()

    with pytest.raises(AShareResearchIntegrityError, match=snapshot_id):
        repository.get_candidate_board(snapshot_id)


def test_diagnosis_snapshot_is_append_only_and_reopenable(tmp_path) -> None:
    database = tmp_path / "a-share-research.sqlite3"
    repository = AShareResearchRepository(database)

    snapshot_id = repository.append_diagnosis(diagnosis())
    stored = repository.get_diagnosis(snapshot_id)

    assert stored.snapshot_id == snapshot_id
    assert stored.symbol == "600000"
    assert stored.input_snapshot_hash
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        repository.connection.execute("DELETE FROM diagnosis_snapshots")
    repository.close()

    reopened = AShareResearchRepository(database)
    assert reopened.get_diagnosis(snapshot_id) == stored
    reopened.close()


def test_repository_verifies_every_snapshot_for_recovery_drill(tmp_path) -> None:
    repository = AShareResearchRepository(tmp_path / "research.sqlite3")
    repository.append_candidate_board(board())
    repository.append_diagnosis(diagnosis())

    assert repository.verify_all() == 2


def test_input_hash_binds_canonical_source_payload(tmp_path) -> None:
    repository = AShareResearchRepository(tmp_path / "research.sqlite3")
    inputs = {
        "bars": [{"symbol": "600000", "close": "10.25"}],
        "market": {"source": "tencent"},
    }

    snapshot_id = repository.append_diagnosis(diagnosis(), input_payload=inputs)
    stored = repository.get_diagnosis(snapshot_id)
    encoded = json.dumps(
        inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )

    assert stored.input_snapshot_hash == hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    repository.connection.execute("DROP TRIGGER reject_update_diagnosis_snapshots")
    repository.connection.execute(
        "UPDATE diagnosis_snapshots SET input_payload='{}' WHERE snapshot_id=?",
        (snapshot_id,),
    )
    repository.connection.commit()
    with pytest.raises(AShareResearchIntegrityError, match="input"):
        repository.get_diagnosis(snapshot_id)
