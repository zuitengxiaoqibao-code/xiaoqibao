from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from qibao_api.dependencies import get_bond_service
from qibao_api.libu_compliance.repository import SourceAuthorizationError


router = APIRouter(prefix="/api/v1/convertible-bonds", tags=["可转债"])


def _authorization_detail(error: SourceAuthorizationError) -> str:
    message = str(error)
    source = "eastmoney" if "eastmoney" in message else "tencent"
    return f"可转债数据源尚未授权：{source}"


@router.get("/status")
@router.get("/dashboard")
def dashboard(service: Annotated[object, Depends(get_bond_service)]):
    return service.dashboard()


@router.get("/candidates")
def candidates(service: Annotated[object, Depends(get_bond_service)]):
    return service.candidates()


@router.get("/{bond_code}/diagnosis")
async def diagnosis(bond_code: str, service: Annotated[object, Depends(get_bond_service)]):
    try:
        return await service.diagnose(bond_code)
    except SourceAuthorizationError as error:
        raise HTTPException(status_code=403, detail=_authorization_detail(error)) from error
