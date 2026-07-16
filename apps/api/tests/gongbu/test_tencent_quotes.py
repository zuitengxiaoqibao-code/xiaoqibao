from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest

from qibao_api.gongbu.tencent_quotes import (
    TencentQuoteSource,
    market_prefix,
    parse_tencent_quote,
    parse_tencent_snapshot,
)


def test_parse_tencent_a_share_quote() -> None:
    fields = [""] * 50
    fields[1] = "浦发银行"
    fields[2] = "600000"
    fields[3] = "10.25"
    fields[4] = "10.10"
    fields[30] = "20260713103000"

    quote = parse_tencent_quote("~".join(fields), source="tencent")

    assert quote.symbol == "600000"
    assert quote.price == Decimal("10.25")
    assert quote.observed_at == datetime(
        2026, 7, 13, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai")
    )


def test_parse_rejects_incomplete_payload() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        parse_tencent_quote("short~payload", source="tencent")


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("600000", "sh"), ("000001", "sz"),
        ("920001", "bj"), ("832000", "bj"), ("430001", "bj"),
    ],
)
def test_market_prefix_uses_exchange_rules(symbol: str, expected: str) -> None:
    assert market_prefix(symbol) == expected


@pytest.mark.asyncio
async def test_source_decodes_gbk_response_and_requests_exchange_symbol() -> None:
    fields = [""] * 50
    fields[1:5] = ["浦发银行", "600000", "10.25", "10.10"]
    fields[30] = "20260713103000"
    body = f'v_sh600000="{"~".join(fields)}";'.encode("gbk")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://qt.gtimg.cn/q=sh600000"
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        quote = await TencentQuoteSource(client).fetch("600000")

    assert quote.name == "浦发银行"


@pytest.mark.asyncio
async def test_source_retries_transport_failure_with_fresh_client() -> None:
    fields = [""] * 50
    fields[1:5] = ["平安银行", "000001", "10.82", "10.84"]
    fields[30] = "20260716095112"
    body = f'v_sz000001="{"~".join(fields)}";'.encode("gbk")

    def failed_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("stale pooled connection", request=request)

    def recovered_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(failed_handler)) as client:
        source = TencentQuoteSource(
            client,
            fallback_client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(recovered_handler)
            ),
        )
        quote = await source.fetch("000001")

    assert quote.symbol == "000001"
    assert quote.name == "平安银行"


def test_tencent_snapshot_parses_valuation_without_field_guessing() -> None:
    fields = [""] * 50
    fields[1] = "浦发银行"
    fields[2] = "600000"
    fields[3] = "10.25"
    fields[4] = "10.10"
    fields[30] = "20260713103000"
    fields[38] = "0.42"
    fields[39] = "6.32"
    fields[44] = "3120.50"
    fields[46] = "0.58"

    snapshot = parse_tencent_snapshot("~".join(fields), source="tencent")

    assert snapshot.pe_ttm == Decimal("6.32")
    assert snapshot.pb == Decimal("0.58")
    assert snapshot.turnover_rate == Decimal("0.42")
    assert snapshot.market_cap_yi == Decimal("3120.50")
    assert snapshot.observed_at == datetime(
        2026, 7, 13, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai")
    )


def test_tencent_snapshot_preserves_missing_valuation_fields() -> None:
    fields = [""] * 50
    fields[1:5] = ["浦发银行", "600000", "10.25", "10.10"]
    fields[30] = "20260713103000"
    fields[38] = "--"

    snapshot = parse_tencent_snapshot("~".join(fields), source="tencent")

    assert snapshot.pe_ttm is None
    assert snapshot.pb is None
    assert snapshot.turnover_rate is None
    assert snapshot.market_cap_yi is None
