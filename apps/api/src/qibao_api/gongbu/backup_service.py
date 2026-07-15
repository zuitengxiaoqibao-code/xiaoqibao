import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import duckdb
from pydantic import BaseModel, ConfigDict, Field


class BackupRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    backup_id: str
    created_at: datetime
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)


class BackupVerification(BaseModel):
    model_config = ConfigDict(frozen=True)
    backup_id: str
    valid: bool
    restore_drill_passed: bool
    checked_files: int = Field(ge=0)
    mismatched_files: tuple[str, ...] = ()


class BackupService:
    def __init__(self, data_dir: Path, bar_repository=None) -> None:
        self.data_dir = data_dir.resolve()
        self.bar_repository = bar_repository
        self.backups_dir = self.data_dir / "backups"
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.registry_path = self.data_dir / "backup-registry.sqlite3"
        self._initialize_registry()

    def create(self) -> BackupRecord:
        with self._lock:
            return self._create_locked()

    def _create_locked(self) -> BackupRecord:
        if self.bar_repository is None:
            raise RuntimeError("bar repository is required to create a backup")
        created_at = datetime.now(timezone.utc)
        backup_id = f"backup-{created_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        temporary = self.backups_dir / f".{backup_id}.tmp"
        final = self.backups_dir / backup_id
        data_target = temporary / "data"
        data_target.mkdir(parents=True)
        try:
            for source in sorted(self.data_dir.iterdir()):
                if source.is_file() and source.suffix in {".sqlite3", ".db"}:
                    self._backup_sqlite(source, data_target / source.name)
            self.bar_repository.backup_to(data_target)
            files = self._file_manifest(data_target)
            manifest = {
                "version": 1,
                "backup_id": backup_id,
                "created_at": created_at.isoformat(),
                "files": files,
            }
            manifest_text = json.dumps(
                manifest, sort_keys=True, separators=(",", ":")
            )
            (temporary / "manifest.json").write_text(manifest_text, encoding="utf-8")
            temporary.rename(final)
            self._register_manifest(
                backup_id, hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
                created_at,
            )
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return BackupRecord(
            backup_id=backup_id,
            created_at=created_at,
            file_count=len(files),
            total_bytes=sum(item["size"] for item in files),
        )

    def verify(self, backup_id: str, *, restore_drill: bool = False) -> BackupVerification:
        root = self._backup_path(backup_id)
        manifest_path = root / "manifest.json"
        try:
            manifest_text = manifest_path.read_text(encoding="utf-8")
            manifest = json.loads(manifest_text)
        except (OSError, ValueError, TypeError):
            return BackupVerification(
                backup_id=backup_id, valid=False, restore_drill_passed=False,
                checked_files=0, mismatched_files=("manifest.json",),
            )
        mismatches = []
        registered_hash = self._registered_hash(backup_id)
        if (
            registered_hash is None
            or registered_hash != hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
        ):
            mismatches.append("manifest.json")
        expected_files = {item["path"] for item in manifest["files"]}
        data_root = (root / "data").resolve()
        actual_files = {
            path.relative_to(data_root).as_posix()
            for path in data_root.rglob("*") if path.is_file()
        }
        mismatches.extend(sorted(expected_files - actual_files))
        mismatches.extend(sorted(actual_files - expected_files))
        for item in manifest["files"]:
            path = (data_root / item["path"]).resolve()
            if (
                path != data_root and data_root not in path.parents
            ):
                mismatches.append(item["path"])
                continue
            if (
                not path.is_file()
                or path.stat().st_size != item["size"]
                or _sha256(path) != item["sha256"]
            ):
                mismatches.append(item["path"])
        mismatches = list(dict.fromkeys(mismatches))
        valid = not mismatches
        drill_passed = False
        if valid and restore_drill:
            drill_passed = self._restore_drill(root / "data")
        return BackupVerification(
            backup_id=backup_id,
            valid=valid,
            restore_drill_passed=drill_passed,
            checked_files=len(manifest["files"]),
            mismatched_files=tuple(mismatches),
        )

    def restore_to(self, backup_id: str, target: Path) -> Path:
        verification = self.verify(backup_id, restore_drill=True)
        if not verification.valid or not verification.restore_drill_passed:
            raise ValueError("backup did not pass verification and restore drill")
        target = target.resolve()
        if target.exists():
            raise FileExistsError("restore target must not exist")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.restore-{uuid4().hex[:8]}"
        try:
            shutil.copytree(self._backup_path(backup_id) / "data", temporary)
            temporary.rename(target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return target

    def _initialize_registry(self) -> None:
        connection = sqlite3.connect(self.registry_path)
        try:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS backup_manifest_registry (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              backup_id TEXT NOT NULL UNIQUE,
              manifest_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS reject_update_backup_registry
            BEFORE UPDATE ON backup_manifest_registry
            BEGIN SELECT RAISE(ABORT, 'append-only backup registry'); END;
            CREATE TRIGGER IF NOT EXISTS reject_delete_backup_registry
            BEFORE DELETE ON backup_manifest_registry
            BEGIN SELECT RAISE(ABORT, 'append-only backup registry'); END;
            """)
            connection.commit()
        finally:
            connection.close()

    def _register_manifest(
        self, backup_id: str, manifest_hash: str, created_at: datetime
    ) -> None:
        connection = sqlite3.connect(self.registry_path)
        try:
            connection.execute(
                """INSERT INTO backup_manifest_registry(
                backup_id,manifest_hash,created_at) VALUES(?,?,?)""",
                (backup_id, manifest_hash, created_at.isoformat()),
            )
            connection.commit()
        finally:
            connection.close()

    def _registered_hash(self, backup_id: str) -> str | None:
        connection = sqlite3.connect(self.registry_path)
        try:
            row = connection.execute(
                "SELECT manifest_hash FROM backup_manifest_registry WHERE backup_id=?",
                (backup_id,),
            ).fetchone()
            return row[0] if row is not None else None
        finally:
            connection.close()

    def backups(self) -> list[BackupRecord]:
        records = []
        for root in sorted(self.backups_dir.glob("backup-*"), reverse=True):
            manifest_path = root / "manifest.json"
            if not manifest_path.is_file():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            records.append(BackupRecord(
                backup_id=manifest["backup_id"],
                created_at=manifest["created_at"],
                file_count=len(manifest["files"]),
                total_bytes=sum(item["size"] for item in manifest["files"]),
            ))
        return records

    def _backup_path(self, backup_id: str) -> Path:
        if not backup_id.startswith("backup-") or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for char in backup_id
        ):
            raise ValueError("invalid backup id")
        path = (self.backups_dir / backup_id).resolve()
        if path.parent != self.backups_dir or not path.is_dir():
            raise FileNotFoundError(backup_id)
        return path

    @staticmethod
    def _backup_sqlite(source: Path, target: Path) -> None:
        source_connection = sqlite3.connect(source)
        target_connection = sqlite3.connect(target)
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
            source_connection.close()

    @staticmethod
    def _file_manifest(root: Path) -> list[dict]:
        return [
            {"path": path.relative_to(root).as_posix(), "size": path.stat().st_size,
             "sha256": _sha256(path)}
            for path in sorted(item for item in root.rglob("*") if item.is_file())
        ]

    @staticmethod
    def _restore_drill(source: Path) -> bool:
        try:
            with tempfile.TemporaryDirectory() as temporary:
                restored = Path(temporary) / "data"
                shutil.copytree(source, restored)
                for path in restored.rglob("*.sqlite3"):
                    connection = sqlite3.connect(path)
                    try:
                        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            return False
                    finally:
                        connection.close()
                for path in restored.glob("*.db"):
                    connection = sqlite3.connect(path)
                    try:
                        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            return False
                    finally:
                        connection.close()
                market = restored / "market.duckdb"
                if market.is_file():
                    connection = duckdb.connect(str(market), read_only=True)
                    try:
                        connection.execute("SELECT COUNT(*) FROM daily_bars").fetchone()
                    finally:
                        connection.close()
                for path in restored.rglob("*.parquet"):
                    connection = duckdb.connect()
                    try:
                        connection.execute(
                            "SELECT COUNT(*) FROM read_parquet(?)", [str(path)]
                        ).fetchone()
                    finally:
                        connection.close()
                BackupService._verify_business_repositories(restored)
            return True
        except Exception:
            return False

    @staticmethod
    def _verify_business_repositories(restored: Path) -> None:
        from qibao_api.a_shares.repository import AShareResearchRepository
        from qibao_api.contracts.market import AssetKind
        from qibao_api.convertible_bonds.diagnosis_repository import (
            BondDiagnosisRepository,
        )
        from qibao_api.dongchang.repository import AuditFindingRepository
        from qibao_api.gongbu.news_repository import NewsRepository
        from qibao_api.hubu.repository import PaperRepository
        from qibao_api.libu_compliance.repository import ComplianceRepository
        from qibao_api.shangshu.briefing_repository import BriefingRepository
        from qibao_api.shangshu.operations_repository import OperationsRepository
        from qibao_api.shangshu.decision_repository import DecisionRepository

        checks = (
            ("news.sqlite3", NewsRepository, lambda repo: (
                repo.events(), repo.interpretations(), repo.corrections()
            )),
            ("briefings.sqlite3", BriefingRepository, lambda repo: (
                repo.reports(), repo.runs()
            )),
            ("compliance.sqlite3", ComplianceRepository, lambda repo: (
                repo.list_current_records(AssetKind.A_SHARE),
                repo.list_current_records(AssetKind.CONVERTIBLE_BOND),
            )),
            ("audit.sqlite3", AuditFindingRepository, lambda repo: (
                repo.list_findings(asset=AssetKind.A_SHARE),
                repo.list_findings(asset=AssetKind.CONVERTIBLE_BOND),
            )),
            ("paper.sqlite3", PaperRepository, lambda repo: repo.list_risk_decisions()),
            ("bond-diagnoses.sqlite3", BondDiagnosisRepository,
             lambda repo: repo.latest_by_bond()),
            ("operations.sqlite3", OperationsRepository, lambda repo: repo.jobs()),
            ("decisions.sqlite3", DecisionRepository, lambda repo: repo.cycles()),
            ("a-share-research.sqlite3", AShareResearchRepository,
             lambda repo: repo.verify_all()),
        )
        for filename, repository_type, read in checks:
            path = restored / filename
            if not path.is_file():
                continue
            repository = repository_type(path)
            try:
                read(repository)
            finally:
                repository.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
