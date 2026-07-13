from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from qibao_api.contracts.research import ResearchCard
from qibao_api.dependencies import get_pipeline
from qibao_api.shangshu.pipeline import ResearchPipeline

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
    return await pipeline.run(symbol)
