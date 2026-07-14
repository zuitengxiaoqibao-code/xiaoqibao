from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, status

from qibao_api.contracts.backtest import BacktestRequest, BacktestResult
from qibao_api.contracts.instruments import AShareCode
from qibao_api.dependencies import get_market_data_service
from qibao_api.gongbu.data_service import MarketDataService
from qibao_api.zhongshu.backtest import BacktestEngine

router = APIRouter(prefix="/api/v1/a-shares", tags=["中书省回测"])


@router.post("/{symbol}/backtests", response_model=BacktestResult)
def run_backtest(
    symbol: Annotated[AShareCode, Path()],
    request: Annotated[BacktestRequest, Body()],
    service: Annotated[MarketDataService, Depends(get_market_data_service)],
) -> BacktestResult:
    bars = service.repository.latest(symbol, 2000)
    if not bars:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="本地没有历史日线，请先在工部同步数据",
        )
    try:
        return BacktestEngine().run(request, bars)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
