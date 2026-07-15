from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
import httpx
from pydantic import BaseModel, ConfigDict

from qibao_api.a_shares.diagnosis import AShareDiagnosis, DiagnosisUnavailableError
from qibao_api.a_shares.instrument_directory import AShareInstrument, AShareInstrumentDirectory
from qibao_api.a_shares.models import CandidateBoard
from qibao_api.a_shares.repository import AShareResearchStoreError
from qibao_api.contracts.instruments import AShareCode, validate_a_share_code
from qibao_api.contracts.market import DataQuality
from qibao_api.contracts.research import ResearchCard
from qibao_api.dependencies import (
    get_a_share_diagnosis_service,
    get_a_share_instrument_directory,
    get_a_share_quote_source,
    get_pipeline,
    get_server_time,
)
from qibao_api.gongbu.tencent_quotes import market_prefix
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.libu_compliance.repository import SourceAuthorizationError

router = APIRouter(prefix="/api/v1/a-shares", tags=["A股"])


class AShareSearchItem(AShareInstrument):
    asset: Literal["a_share"] = "a_share"


class AShareSearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    items: tuple[AShareSearchItem, ...]
    server_time: datetime
    source_status: Literal["ready", "unavailable"] = "ready"


def _quote_observed_at(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return value


def _quote_quality(value: DataQuality) -> Literal["ready", "stale", "unavailable"]:
    if value == DataQuality.FRESH:
        return "ready"
    if value == DataQuality.STALE:
        return "stale"
    return "unavailable"


@router.get("/search", response_model=AShareSearchResponse)
async def search_instruments(
    directory: Annotated[AShareInstrumentDirectory, Depends(get_a_share_instrument_directory)],
    quote_source: Annotated[object, Depends(get_a_share_quote_source)],
    server_time: Annotated[datetime, Depends(get_server_time)],
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> AShareSearchResponse:
    query = q.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="q must not be empty",
        )
    items = directory.search(query, limit)
    source_status: Literal["ready", "unavailable"] = "ready"
    try:
        exact_symbol = validate_a_share_code(query)
    except ValueError:
        exact_symbol = None
    resolved = directory.resolve(exact_symbol) if exact_symbol is not None else None
    if exact_symbol is not None and (resolved is None or resolved.name == exact_symbol):
        try:
            quote = await quote_source.fetch(exact_symbol)
            if quote.symbol != exact_symbol:
                raise ValueError("Tencent quote symbol does not match requested A-share")
            instrument = AShareInstrument(
                symbol=quote.symbol,
                name=quote.name,
                exchange=market_prefix(quote.symbol),
                observed_at=_quote_observed_at(quote.observed_at),
                quote_quality=_quote_quality(quote.quality),
            )
        except (httpx.HTTPError, ValueError):
            items = ()
            source_status = "unavailable"
        else:
            directory.observe(instrument)
            items = (instrument,)
    return AShareSearchResponse(
        query=query,
        items=tuple(AShareSearchItem(**item.model_dump()) for item in items),
        server_time=server_time,
        source_status=source_status,
    )


def _beijing_today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def _research_date(value: date | None) -> date:
    today = _beijing_today()
    result = value or today
    if result > today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "future_as_of_not_allowed",
                "message": "研究截止日期不能晚于北京时间今天",
            },
        )
    return result


def _store_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "a_share_research_store_error",
            "message": "A 股研究存档暂不可用",
        },
    )


@router.get("/candidates", response_model=CandidateBoard)
def candidates(
    service: Annotated[object, Depends(get_a_share_diagnosis_service)],
    as_of: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CandidateBoard:
    try:
        return service.candidates(_research_date(as_of), limit)
    except AShareResearchStoreError as error:
        raise _store_error() from error


@router.get("/{symbol}/diagnosis", response_model=AShareDiagnosis)
async def diagnosis(
    symbol: Annotated[AShareCode, Path()],
    service: Annotated[object, Depends(get_a_share_diagnosis_service)],
    as_of: date | None = None,
) -> AShareDiagnosis:
    try:
        return await service.diagnose(symbol, _research_date(as_of))
    except SourceAuthorizationError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "source_authorization_required",
                "message": "请先在礼部完成 A 股行情和财务数据授权",
            },
        ) from error
    except DiagnosisUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "a_share_diagnosis_unavailable",
                "message": "A 股基础行情和本地历史均不可用",
            },
        ) from error
    except AShareResearchStoreError as error:
        raise _store_error() from error

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
