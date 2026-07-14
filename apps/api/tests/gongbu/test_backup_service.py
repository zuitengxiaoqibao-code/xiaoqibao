import json
import sqlite3
from datetime import date
from decimal import Decimal

from qibao_api.contracts.bars import DailyBar
from qibao_api.gongbu.backup_service import BackupService
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
