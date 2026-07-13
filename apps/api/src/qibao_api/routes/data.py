from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from qibao_api.contracts.bars import DailyBar, SyncReport
from qibao_api.dependencies import get_market_data_service
from qibao_api.gongbu.data_service import MarketDataService
from qibao_api.routes.research import A_SHARE_SYMBOL

router = APIRouter(prefix="/api/v1/a-shares", tags=["工部数据"])


@router.post("/{symbol}/history/sync", response_model=SyncReport)
def sync_history(
    symbol: Annotated[str, Path(pattern=A_SHARE_SYMBOL)],
    service: Annotated[MarketDataService, Depends(get_market_data_service)],
    limit: Annotated[int, Query(ge=1, le=2000)] = 250,
) -> SyncReport:
    return service.sync_symbol(symbol, limit)


@router.get("/{symbol}/history", response_model=list[DailyBar])
def history(
    symbol: Annotated[str, Path(pattern=A_SHARE_SYMBOL)],
    service: Annotated[MarketDataService, Depends(get_market_data_service)],
    limit: Annotated[int, Query(ge=1, le=2000)] = 250,
) -> list[DailyBar]:
    return service.repository.latest(symbol, limit)

