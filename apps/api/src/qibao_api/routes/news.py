from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException

from qibao_api.contracts.news import NormalizedNewsEvent
from qibao_api.dependencies import get_news_repository, get_news_service
from qibao_api.gongbu.news_repository import NewsIntegrityError
from qibao_api.libu_compliance.repository import SourceAuthorizationError


router = APIRouter(prefix="/api/v1/news", tags=["工部新闻"])


@router.post("/sync")
async def sync_news(service: Annotated[object, Depends(get_news_service)]):
    try:
        return await service.sync()
    except SourceAuthorizationError as error:
        raise HTTPException(
            status_code=403, detail="A 股新闻数据源尚未授权：eastmoney"
        ) from error
    except (OSError, httpx.HTTPError) as error:
        raise HTTPException(
            status_code=502,
            detail={"code": "news_upstream_unavailable", "message": "新闻源暂不可用"},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_news_data", "message": "新闻数据格式无法验证"},
        ) from error


@router.get("/events", response_model=list[NormalizedNewsEvent])
def news_events(repository: Annotated[object, Depends(get_news_repository)]):
    try:
        return repository.events()
    except NewsIntegrityError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "news_integrity_error", "message": "新闻证据存档校验失败"},
        ) from error
