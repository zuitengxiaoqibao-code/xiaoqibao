from datetime import datetime
from decimal import Decimal

import httpx
import pytest

from qibao_api.gongbu.tencent_quotes import (
    TencentQuoteSource,
    market_prefix,
    parse_tencent_quote,
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
    assert quote.observed_at == datetime(2026, 7, 13, 10, 30)


def test_parse_rejects_incomplete_payload() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        parse_tencent_quote("short~payload", source="tencent")


@pytest.mark.parametrize(("symbol", "expected"), [("600000", "sh"), ("000001", "sz")])
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
