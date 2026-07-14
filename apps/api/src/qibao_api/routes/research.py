from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from qibao_api.contracts.research import ResearchCard
from qibao_api.dependencies import get_pipeline
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.libu_compliance.repository import SourceAuthorizationError

router = APIRouter(prefix="/api/v1/a-shares", tags=["A股"])

A_SHARE_SYMBOL = r"^\d{6}$"
CONVERTIBLE_BOND_PREFIXES = ("11", "12")


@router.get("/{symbol}/snapshot", response_model=ResearchCard)
async def snapshot(
    symbol: Annotated[str, Path(pattern=A_SHARE_SYMBOL)],
    pipeline: Annotated[ResearchPipeline, Depends(get_pipeline)],
) -> ResearchCard:
    if symbol.startswith(CONVERTIBLE_BOND_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="可转债代码不能进入 A 股研究路由",
        )
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
