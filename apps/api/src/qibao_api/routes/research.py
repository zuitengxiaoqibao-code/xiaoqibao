from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from qibao_api.contracts.instruments import AShareCode
from qibao_api.contracts.research import ResearchCard
from qibao_api.dependencies import get_pipeline
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.libu_compliance.repository import SourceAuthorizationError

router = APIRouter(prefix="/api/v1/a-shares", tags=["A股"])

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
