import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from qibao_api.contracts.market import AssetKind, DataQuality
from qibao_api.convertible_bonds.adapters import (
    EastmoneyClauseSource,
    RawHttpResponse,
    TencentBondQuoteSource,
)


def tencent_body(
    *, code: str = "113001", price: str = "121.50", timestamp: str = "20260714103000"
) -> bytes:
    fields = [""] * 31
    fields[1] = "\u6d66\u53d1\u8f6c\u503a"
    fields[2] = code
    fields[3] = price
    fields[4] = "120.00"
    fields[30] = timestamp
    return ('v_sh113001="' + "~".join(fields) + '";').encode("gbk")


@pytest.mark.asyncio
async def test_tencent_adapter_decodes_gbk_and_preserves_raw_identity() -> None:
    raw = tencent_body()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/q=sh113001"
        return httpx.Response(200, content=raw)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        quote = await TencentBondQuoteSource(client).fetch("113001")

    assert quote.asset is AssetKind.CONVERTIBLE_BOND
    assert quote.symbol == "113001"
    assert quote.name == "\u6d66\u53d1\u8f6c\u503a"
    assert quote.price == Decimal("121.50")
    assert quote.source == "tencent"
    assert quote.observed_at == datetime(
        2026, 7, 14, 10, 30, tzinfo=timezone(timedelta(hours=8))
    )
    assert quote.quality is DataQuality.FRESH
    assert quote.raw_identity


@pytest.mark.asyncio
async def test_tencent_adapter_rejects_provider_code_mismatch() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=tencent_body(code="113002"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="does not match requested bond"):
            await TencentBondQuoteSource(client).fetch("113001")


@pytest.mark.asyncio
async def test_tencent_adapter_marks_zero_price_as_suspended() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=tencent_body(price="0"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        quote = await TencentBondQuoteSource(client).fetch("113001")

    assert quote.price is None
    assert quote.suspended is True
    assert quote.quality is DataQuality.UNAVAILABLE


@pytest.mark.asyncio
async def test_tencent_adapter_rejects_incomplete_payload() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'v_sh113001="too~short";')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="incomplete"):
            await TencentBondQuoteSource(client).fetch("113001")


def eastmoney_body(*, code: str = "113001", price: str = "9.87") -> bytes:
    return json.dumps({
        "version": "1f8d9b",
        "result": {"pages": 1, "data": [{
            "SECURITY_CODE": code,
            "CONVERT_STOCK_CODE": "600000",
            "CONVERT_PRICE": price,
            "REMAIN_SIZE": "12.345678",
            "MATURITY_DATE": "2030-07-14 00:00:00",
            "CONVERT_START_DATE": "2026-01-01 00:00:00",
            "REDEEM_START_DATE": "2026-07-01 00:00:00",
            "PUTBACK_START_DATE": "2029-01-01 00:00:00",
            "REDEEM_CLAUSE": "provider text",
            "PUTBACK_CLAUSE": "provider text",
        }]},
    }, separators=(",", ":")).encode()


@pytest.mark.asyncio
async def test_eastmoney_source_builds_real_request_and_maps_provider_fields() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    async def transport(url: str, params: dict[str, str]) -> RawHttpResponse:
        seen.append((url, params))
        return RawHttpResponse(status_code=200, body=eastmoney_body())

    def clock() -> datetime:
        return datetime(2026, 7, 14, tzinfo=timezone.utc)

    snapshot = await EastmoneyClauseSource(transport=transport, clock=clock).fetch("113001")

    assert seen[0][0] == "https://datacenter-web.eastmoney.com/api/data/v1/get"
    assert seen[0][1]["reportName"] == "RPT_BOND_CB_LIST"
    assert seen[0][1]["filter"] == '(SECURITY_CODE="113001")'
    assert snapshot.contract.linked_stock == "600000"
    assert snapshot.contract.conversion_price == Decimal("9.87")
    assert snapshot.source == "eastmoney"
    assert snapshot.raw_payload == eastmoney_body()
    assert snapshot.fetched_at == clock()


@pytest.mark.asyncio
async def test_eastmoney_source_rejects_status_and_provider_code_mismatch() -> None:
    async def bad_status(_: str, __: dict[str, str]) -> RawHttpResponse:
        return RawHttpResponse(status_code=503, body=b"unavailable")

    with pytest.raises(ValueError, match="status 503"):
        await EastmoneyClauseSource(transport=bad_status).fetch("113001")

    async def wrong_code(_: str, __: dict[str, str]) -> RawHttpResponse:
        return RawHttpResponse(status_code=200, body=eastmoney_body(code="113002"))

    with pytest.raises(ValueError, match="does not match requested bond"):
        await EastmoneyClauseSource(transport=wrong_code).fetch("113001")


@pytest.mark.asyncio
async def test_eastmoney_source_rejects_missing_linked_stock() -> None:
    raw = json.loads(eastmoney_body())
    del raw["result"]["data"][0]["CONVERT_STOCK_CODE"]

    async def transport(_: str, __: dict[str, str]) -> RawHttpResponse:
        return RawHttpResponse(status_code=200, body=json.dumps(raw).encode())

    with pytest.raises(ValueError, match="CONVERT_STOCK_CODE"):
        await EastmoneyClauseSource(transport=transport).fetch("113001")
