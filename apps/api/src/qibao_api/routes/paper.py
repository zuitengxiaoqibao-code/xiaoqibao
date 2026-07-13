from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from qibao_api.bingbu.paper_broker import PaperOrderResult
from qibao_api.bingbu.paper_service import DecisionPersistenceUnavailable, PaperTradingService
from qibao_api.contracts.trading import LedgerEntry, OrderRequest, PaperAccount, Position
from qibao_api.dependencies import get_paper_repository, get_paper_service
from qibao_api.hubu.repository import PaperRepository

router = APIRouter(prefix="/api/v1/paper", tags=["模拟交易"])


class AccountCreate(BaseModel):
    account_id: str = Field(min_length=1, max_length=64)
    initial_cash: Decimal = Field(gt=0)


@router.post("/accounts", response_model=PaperAccount, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreate,
    repository: Annotated[PaperRepository, Depends(get_paper_repository)],
) -> PaperAccount:
    try:
        return repository.create_account(payload.account_id, payload.initial_cash)
    except Exception as error:
        if "UNIQUE constraint" in str(error):
            raise HTTPException(status_code=409, detail="模拟账户已存在") from error
        raise


@router.get("/accounts/{account_id}", response_model=PaperAccount)
def get_account(
    account_id: str,
    repository: Annotated[PaperRepository, Depends(get_paper_repository)],
) -> PaperAccount:
    try:
        return repository.get_account(account_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="模拟账户不存在") from error


@router.get("/accounts/{account_id}/positions", response_model=list[Position])
def list_positions(
    account_id: str,
    repository: Annotated[PaperRepository, Depends(get_paper_repository)],
) -> list[Position]:
    get_account(account_id, repository)
    return repository.list_positions(account_id)


@router.get("/accounts/{account_id}/ledger", response_model=list[LedgerEntry])
def list_ledger(
    account_id: str,
    repository: Annotated[PaperRepository, Depends(get_paper_repository)],
) -> list[LedgerEntry]:
    get_account(account_id, repository)
    return repository.list_ledger(account_id)


@router.get("/accounts/{account_id}/orders")
def list_orders(
    account_id: str,
    repository: Annotated[PaperRepository, Depends(get_paper_repository)],
) -> list[dict[str, object]]:
    get_account(account_id, repository)
    return repository.list_orders(account_id)


@router.post("/accounts/{account_id}/orders", response_model=PaperOrderResult)
async def submit_order(
    account_id: str,
    payload: OrderRequest,
    service: Annotated[PaperTradingService, Depends(get_paper_service)],
) -> PaperOrderResult:
    try:
        return await service.submit(account_id, payload)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="模拟账户不存在") from error
    except DecisionPersistenceUnavailable as error:
        raise HTTPException(status_code=503, detail="risk_decision_persistence_unavailable") from error
