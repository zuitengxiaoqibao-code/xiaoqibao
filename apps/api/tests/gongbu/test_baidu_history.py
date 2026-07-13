import httpx
import pytest

from qibao_api.gongbu.baidu_history import BaiduHistorySource


@pytest.mark.asyncio
async def test_baidu_history_parses_keyed_market_rows() -> None:
    payload = {
        "ResultCode": 0,
        "Result": {
            "newMarketData": {
                "keys": ["timestamp", "time", "open", "close", "volume", "high", "low", "amount"],
                "marketData": "1783872000,2026-07-13,9.04,9.19,75761962,9.21,9.01,693325381.00",
            }
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["code"] == "600000"
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        bars = BaiduHistorySource(client).fetch_daily("600000", 20)

    assert len(bars) == 1
    assert bars[0].source == "baidu"
    assert str(bars[0].close) == "9.19"

