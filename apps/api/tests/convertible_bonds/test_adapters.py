from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from qibao_api.contracts.market import AssetKind, DataQuality
from qibao_api.convertible_bonds.adapters import (
    EastmoneyClauseSource,
    TencentBondQuoteSource,
    parse_eastmoney_clause_payload,
)


def tencent_body(*, price: str = "121.50", timestamp: str = "20260714103000") -> bytes:
    fields = [""] * 31
    fields[1] = "\u6d66\u53d1\u8f6c\u503a"
    fields[2] = "113001"
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


def clause_payload(*, linked_stock: str | None = "600000", price: str = "9.87") -> dict:
    return {
        "bond_code": "113001",
        "linked_stock": linked_stock,
        "conversion_price": price,
        "maturity": "2030-07-14",
        "remaining_size": "12.345678",
        "conversion_start": "2026-01-01",
        "redemption_start": "2026-07-01",
        "put_back_start": "2029-01-01",
    }


def test_clause_parser_normalizes_real_fields_without_inventing_values() -> None:
    fetched_at = datetime(2026, 7, 14, 3, tzinfo=timezone.utc)
    snapshot = parse_eastmoney_clause_payload(clause_payload(), fetched_at=fetched_at)

    assert snapshot.contract.bond_code == "113001"
    assert snapshot.contract.linked_stock == "600000"
    assert snapshot.contract.conversion_price == Decimal("9.87")
    assert snapshot.contract.maturity == date(2030, 7, 14)
    assert snapshot.source == "eastmoney"
    assert snapshot.fetched_at == fetched_at
    assert snapshot.content_hash


def test_clause_parser_rejects_missing_linked_stock() -> None:
    with pytest.raises(ValueError, match="linked_stock"):
        parse_eastmoney_clause_payload(
            clause_payload(linked_stock=None),
            fetched_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_clause_source_uses_injected_transport() -> None:
    seen: list[str] = []

    async def transport(code: str) -> dict:
        seen.append(code)
        return clause_payload()

    def clock() -> datetime:
        return datetime(2026, 7, 14, tzinfo=timezone.utc)

    snapshot = await EastmoneyClauseSource(transport, clock=clock).fetch("113001")

    assert seen == ["113001"]
    assert snapshot.contract.bond_code == "113001"
