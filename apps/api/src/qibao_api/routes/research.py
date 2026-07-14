from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from qibao_api.a_shares.diagnosis import AShareDiagnosis, DiagnosisUnavailableError
from qibao_api.a_shares.models import CandidateBoard
from qibao_api.a_shares.repository import AShareResearchIntegrityError
from qibao_api.contracts.instruments import AShareCode
from qibao_api.contracts.research import ResearchCard
from qibao_api.dependencies import get_a_share_diagnosis_service, get_pipeline
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.libu_compliance.repository import SourceAuthorizationError

router = APIRouter(prefix="/api/v1/a-shares", tags=["A股"])


def _beijing_today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


@router.get("/candidates", response_model=CandidateBoard)
def candidates(
    service: Annotated[object, Depends(get_a_share_diagnosis_service)],
    as_of: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CandidateBoard:
    try:
        return service.candidates(as_of or _beijing_today(), limit)
    except AShareResearchIntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "a_share_research_integrity_error",
                "message": "A 股研究存档校验失败",
            },
        ) from error


@router.get("/{symbol}/diagnosis", response_model=AShareDiagnosis)
async def diagnosis(
    symbol: Annotated[AShareCode, Path()],
    service: Annotated[object, Depends(get_a_share_diagnosis_service)],
    as_of: date | None = None,
) -> AShareDiagnosis:
    try:
        return await service.diagnose(symbol, as_of or _beijing_today())
    except DiagnosisUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "a_share_diagnosis_unavailable",
                "message": "A 股基础行情和本地历史均不可用",
            },
        ) from error
    except AShareResearchIntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "a_share_research_integrity_error",
                "message": "A 股研究存档校验失败",
            },
        ) from error

@router.get("/{symbol}/snapshot", response_model=ResearchCard)
async def snapshot(
    symbol: Annotated[AShareCode, Path()],
    pipeline: Annotated[ResearchPipeline, Depends(get_pipeline)],
) -> ResearchCard:
    try:
        return await pipeline.run(symbol)
    except SourceAuthorizationError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "source_authorization_required",
                "message": "请先在礼部完成腾讯行情授权并确认免责声明",
            },
        ) from error
