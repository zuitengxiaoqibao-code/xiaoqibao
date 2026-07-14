from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from qibao_api.contracts.briefing import BriefingPhase
from qibao_api.dependencies import get_backup_service, get_scheduler
from qibao_api.gongbu.backup_service import BackupRecord, BackupVerification


router = APIRouter(prefix="/api/v1/operations", tags=["工部运维"])


@router.get("/status")
def operations_status(
    scheduler: Annotated[object, Depends(get_scheduler)],
    backups: Annotated[object, Depends(get_backup_service)],
):
    return {"scheduler": scheduler.status(), "backups": backups.backups()}


@router.post("/scheduler/{action}")
def scheduler_action(
    action: str,
    scheduler: Annotated[object, Depends(get_scheduler)],
):
    if action not in {"pause", "resume"}:
        raise HTTPException(status_code=404, detail="未知调度操作")
    scheduler.set_paused(action == "pause", datetime.now(timezone.utc))
    return scheduler.status()


@router.post("/jobs/{phase}/{trading_date}/run")
def run_manual_job(
    phase: BriefingPhase,
    trading_date: date,
    scheduler: Annotated[object, Depends(get_scheduler)],
):
    report = scheduler.run_manual(
        phase, trading_date, datetime.now(timezone.utc)
    )
    if report is None:
        raise HTTPException(status_code=503, detail="手动补跑失败，已记录运行日志")
    return {"report_id": report.report_id}


@router.get("/backups", response_model=list[BackupRecord])
def list_backups(backups: Annotated[object, Depends(get_backup_service)]):
    return backups.backups()


@router.post("/backups", response_model=BackupRecord)
def create_backup(backups: Annotated[object, Depends(get_backup_service)]):
    return backups.create()


@router.post("/backups/{backup_id}/verify", response_model=BackupVerification)
def verify_backup(
    backup_id: str,
    backups: Annotated[object, Depends(get_backup_service)],
    restore_drill: Annotated[bool, Query()] = True,
):
    try:
        return backups.verify(backup_id, restore_drill=restore_drill)
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=404, detail="备份不存在或标识无效") from error
