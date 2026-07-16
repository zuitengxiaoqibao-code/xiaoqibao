from typing import Annotated
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.news import (
    AIInterpretation,
    NewsCorrection,
    NormalizedNewsEvent,
)
from qibao_api.dependencies import get_news_repository, get_news_service
from qibao_api.gongbu.news_repository import NewsIntegrityError
from qibao_api.libu_compliance.repository import SourceAuthorizationError
from qibao_api.zhongshu.news_quality import NewsQualityMetrics, NewsQualityService


router = APIRouter(prefix="/api/v1/news", tags=["工部新闻"])


class CorrectionRequest(BaseModel):
    event_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    review_state: Literal["pending", "verified", "rejected"]
    affected_instruments: tuple[tuple[AssetKind, str], ...] = ()
    industries: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()


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


@router.get("/interpretations", response_model=list[AIInterpretation])
def news_interpretations(repository: Annotated[object, Depends(get_news_repository)]):
    try:
        return repository.interpretations()
    except NewsIntegrityError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "news_integrity_error", "message": "新闻解释存档校验失败"},
        ) from error


@router.get("/quality", response_model=NewsQualityMetrics)
def news_quality(repository: Annotated[object, Depends(get_news_repository)]):
    try:
        return NewsQualityService(repository).metrics()
    except NewsIntegrityError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "news_integrity_error", "message": "新闻质量数据校验失败"},
        ) from error


@router.post("/corrections", response_model=NewsCorrection)
def create_correction(
    request: CorrectionRequest,
    repository: Annotated[object, Depends(get_news_repository)],
):
    correction = NewsCorrection(
        correction_id=f"correction-{uuid4().hex}",
        event_id=request.event_id,
        corrected_at=datetime.now(timezone.utc),
        reason=request.reason,
        review_state=request.review_state,
        affected_instruments=request.affected_instruments,
        industries=request.industries,
        themes=request.themes,
    )
    try:
        repository.append_correction(correction)
    except NewsIntegrityError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return correction


@router.get("/corrections", response_model=list[NewsCorrection])
def news_corrections(repository: Annotated[object, Depends(get_news_repository)]):
    try:
        return repository.corrections()
    except NewsIntegrityError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "news_integrity_error", "message": "新闻修正存档校验失败"},
        ) from error
