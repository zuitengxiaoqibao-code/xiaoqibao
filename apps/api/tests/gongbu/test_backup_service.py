import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

from qibao_api.contracts.bars import DailyBar
from qibao_api.gongbu.backup_service import BackupService
from qibao_api.gongbu.fund_flow import FundFlowRepository, FundFlowSnapshot
from qibao_api.storage.bar_repository import BarRepository


def test_backup_captures_live_databases_and_passes_restore_drill(tmp_path) -> None:
    data_dir = tmp_path / "runtime"
    data_dir.mkdir()
    sqlite_path = data_dir / "paper.sqlite3"
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("CREATE TABLE ledger(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO ledger(value) VALUES('frozen')")
    bars = BarRepository(data_dir / "market.duckdb", data_dir / "parquet" / "a-shares")
    bars.upsert([DailyBar(
        symbol="600000", trade_date=date(2026, 7, 14), open=Decimal("10"),
        high=Decimal("11"), low=Decimal("9"), close=Decimal("10.5"),
        volume=1000, amount=Decimal("10000"), source="fixture",
    )])
    bars.export_parquet("600000")
    service = BackupService(data_dir, bars)

    created = service.create()
    verification = service.verify(created.backup_id, restore_drill=True)

    assert created.file_count >= 3
    assert verification.valid is True
    assert verification.restore_drill_passed is True
    manifest = json.loads((data_dir / "backups" / created.backup_id / "manifest.json").read_text("utf-8"))
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])


def test_backup_verification_detects_tampering(tmp_path) -> None:
    data_dir = tmp_path / "runtime"
    data_dir.mkdir()
    with sqlite3.connect(data_dir / "audit.sqlite3") as connection:
        connection.execute("CREATE TABLE findings(id INTEGER PRIMARY KEY)")
    bars = BarRepository(data_dir / "market.duckdb", data_dir / "parquet" / "a-shares")
    service = BackupService(data_dir, bars)
    created = service.create()
    payload = data_dir / "backups" / created.backup_id / "data" / "audit.sqlite3"
    payload.write_bytes(payload.read_bytes() + b"tampered")

    verification = service.verify(created.backup_id, restore_drill=True)

    assert verification.valid is False
    assert verification.restore_drill_passed is False
    assert "audit.sqlite3" in verification.mismatched_files


def test_backup_rejects_manifest_omissions_and_unlisted_files(tmp_path) -> None:
    data_dir = tmp_path / "runtime"
    data_dir.mkdir()
    with sqlite3.connect(data_dir / "news.sqlite3") as connection:
        connection.execute("CREATE TABLE events(id INTEGER PRIMARY KEY)")
    bars = BarRepository(data_dir / "market.duckdb", data_dir / "parquet" / "a-shares")
    service = BackupService(data_dir, bars)
    created = service.create()
    root = data_dir / "backups" / created.backup_id
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["files"] = manifest["files"][1:]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (root / "data" / "unlisted.bin").write_bytes(b"extra")

    verification = service.verify(created.backup_id, restore_drill=True)

    assert verification.valid is False
    assert "manifest.json" in verification.mismatched_files
    assert "unlisted.bin" in verification.mismatched_files


def test_verified_backup_restores_only_to_a_new_empty_directory(tmp_path) -> None:
    data_dir = tmp_path / "runtime"
    data_dir.mkdir()
    with sqlite3.connect(data_dir / "paper.sqlite3") as connection:
        connection.execute("CREATE TABLE accounts(id INTEGER PRIMARY KEY)")
    bars = BarRepository(data_dir / "market.duckdb", data_dir / "parquet" / "a-shares")
    service = BackupService(data_dir, bars)
    created = service.create()
    target = tmp_path / "restored-runtime"

    restored = service.restore_to(created.backup_id, target)

    assert restored == target.resolve()
    assert (target / "paper.sqlite3").is_file()
    assert (target / "market.duckdb").is_file()
    with sqlite3.connect(target / "paper.sqlite3") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_restore_drill_verifies_decision_repository_hash_chain(tmp_path) -> None:
    from qibao_api.shangshu.decision_repository import DecisionRepository

    data_dir = tmp_path / "runtime"
    data_dir.mkdir()
    decisions = DecisionRepository(data_dir / "decisions.sqlite3")
    decisions.close()
    bars = BarRepository(data_dir / "market.duckdb", data_dir / "parquet" / "a-shares")
    service = BackupService(data_dir, bars)
    created = service.create()

    assert service.verify(created.backup_id, restore_drill=True).restore_drill_passed is True


def test_restore_drill_rejects_tampered_fund_flow_business_hash(tmp_path) -> None:
    data_dir = tmp_path / "runtime"
    data_dir.mkdir()
    repository = FundFlowRepository(data_dir / "fund-flow.sqlite3")
    raw_snapshot = b'{"daily":{},"minute":{}}'
    content_hash = hashlib.sha256(b"verified-fund-flow").hexdigest()
    repository.append(FundFlowSnapshot(
        snapshot_id="fund-flow-" + "a" * 24,
        symbol="600519",
        observed_at=datetime(2026, 7, 17, 6, tzinfo=timezone.utc),
        latest_trade_date=date(2026, 7, 17),
        latest_main_net=Decimal("100000000"),
        latest_super_net=Decimal("60000000"),
        latest_large_net=Decimal("40000000"),
        main_net_5d=Decimal("300000000"),
        main_net_20d=Decimal("700000000"),
        intraday_main_net=Decimal("80000000"),
        daily_sample_count=20,
        intraday_sample_count=120,
        flow_direction="inflow",
        content_hash=content_hash,
        raw_snapshot=raw_snapshot,
    ))
    repository.close()
    bars = BarRepository(
        data_dir / "market.duckdb", data_dir / "parquet" / "a-shares"
    )
    service = BackupService(data_dir, bars)
    created = service.create()
    backup_data = data_dir / "backups" / created.backup_id / "data"
    database = backup_data / "fund-flow.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER reject_update_fund_flow_snapshots")
        connection.execute(
            "UPDATE fund_flow_snapshots SET raw_snapshot=?",
            (b'{"daily":{"tampered":true},"minute":{}}',),
        )

    assert BackupService._restore_drill(backup_data) is False
