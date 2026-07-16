from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from qibao_api.contracts.briefing import BriefingPhase, DailyBriefing
from qibao_api.dependencies import get_briefing_repository, get_briefing_workflow
from qibao_api.shangshu.briefing_repository import BriefingIntegrityError


router = APIRouter(prefix="/api/v1/briefings", tags=["尚书省每日简报"])


@router.post("/{phase}/{trading_date}/run", response_model=DailyBriefing)
def run_briefing(
    phase: BriefingPhase,
    trading_date: date,
    workflow: Annotated[object, Depends(get_briefing_workflow)],
):
    try:
        return workflow.run(phase, trading_date)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except BriefingIntegrityError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "briefing_integrity_error", "message": "简报存档校验失败"},
        ) from error


@router.get("", response_model=list[DailyBriefing])
def list_briefings(
    repository: Annotated[object, Depends(get_briefing_repository)],
    phase: Annotated[BriefingPhase | None, Query()] = None,
    trading_date: Annotated[date | None, Query()] = None,
):
    try:
        return repository.reports(phase=phase, trading_date=trading_date)
    except BriefingIntegrityError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "briefing_integrity_error", "message": "简报存档校验失败"},
        ) from error
