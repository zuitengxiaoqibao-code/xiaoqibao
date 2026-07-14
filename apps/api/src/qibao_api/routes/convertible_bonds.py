from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
import httpx

from qibao_api.dependencies import get_bond_service
from qibao_api.libu_compliance.repository import SourceAuthorizationError
from qibao_api.convertible_bonds.adapters import ClauseDataUnavailable
from qibao_api.convertible_bonds.diagnosis_repository import DataIntegrityError


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
    try:
        return service.candidates()
    except DataIntegrityError as error:
        raise HTTPException(status_code=503, detail={"code": "diagnosis_integrity_error", "message": "转债诊断存档校验失败"}) from error


@router.get("/{bond_code}/diagnosis")
async def diagnosis(bond_code: str, service: Annotated[object, Depends(get_bond_service)]):
    try:
        return await service.diagnose(bond_code)
    except SourceAuthorizationError as error:
        raise HTTPException(status_code=403, detail=_authorization_detail(error)) from error
    except ClauseDataUnavailable as error:
        raise HTTPException(status_code=404, detail={"code": "clauses_unavailable", "message": "未查询到可转债条款数据"}) from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail={"code": "upstream_unavailable", "message": "上游数据源暂不可用"}) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "invalid_provider_data", "message": "上游数据格式无法验证"}) from error
