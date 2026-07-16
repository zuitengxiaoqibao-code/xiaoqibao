from datetime import UTC, date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qibao_api.dependencies import get_backup_service, get_scheduler
from qibao_api.gongbu.backup_service import BackupRecord, BackupVerification
from qibao_api.routes.operations import router


NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


class Scheduler:
    def __init__(self):
        self.paused = False
        self.manual = []

    def status(self):
        return {"paused": self.paused, "jobs": []}

    def set_paused(self, value, now):
        self.paused = value

    def run_manual(self, phase, trading_date, now):
        self.manual.append((phase, trading_date))
        return type("Report", (), {"report_id": "report-manual"})()


class Backups:
    def backups(self):
        return [BackupRecord(backup_id="backup-1", created_at=NOW, file_count=3, total_bytes=42)]

    def create(self):
        return BackupRecord(backup_id="backup-2", created_at=NOW, file_count=4, total_bytes=84)

    def verify(self, backup_id, *, restore_drill):
        assert restore_drill is True
        return BackupVerification(backup_id=backup_id, valid=True,
                                  restore_drill_passed=True, checked_files=4)


def test_operations_routes_control_scheduler_and_manual_run() -> None:
    scheduler = Scheduler()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_scheduler] = lambda: scheduler
    app.dependency_overrides[get_backup_service] = lambda: Backups()
    client = TestClient(app)

    paused = client.post("/api/v1/operations/scheduler/pause")
    status = client.get("/api/v1/operations/status")
    manual = client.post("/api/v1/operations/jobs/postclose/2026-07-14/run")
    resumed = client.post("/api/v1/operations/scheduler/resume")

    assert paused.status_code == 200
    assert status.json()["scheduler"]["paused"] is True
    assert status.json()["backups"][0]["backup_id"] == "backup-1"
    assert manual.json()["report_id"] == "report-manual"
    assert scheduler.manual == [("postclose", date(2026, 7, 14))]
    assert resumed.json()["paused"] is False


def test_operations_routes_create_and_restore_verify_backup() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_scheduler] = lambda: Scheduler()
    app.dependency_overrides[get_backup_service] = lambda: Backups()
    client = TestClient(app)

    created = client.post("/api/v1/operations/backups")
    verified = client.post("/api/v1/operations/backups/backup-2/verify?restore_drill=true")

    assert created.status_code == 200
    assert created.json()["file_count"] == 4
    assert verified.json()["valid"] is True
    assert verified.json()["restore_drill_passed"] is True
