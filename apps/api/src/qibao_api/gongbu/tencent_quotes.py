from datetime import datetime
from decimal import Decimal

import httpx

from qibao_api.contracts.market import AssetKind, DataQuality, Quote


def market_prefix(symbol: str) -> str:
    return "sh" if symbol.startswith(("5", "6", "9")) else "sz"


def parse_tencent_quote(payload: str, source: str) -> Quote:
    fields = payload.split("~")
    if len(fields) < 31:
        raise ValueError("Tencent quote payload is incomplete")
    return Quote(
        symbol=fields[2],
        asset=AssetKind.A_SHARE,
        name=fields[1],
        price=Decimal(fields[3]),
        previous_close=Decimal(fields[4]),
        observed_at=datetime.strptime(fields[30], "%Y%m%d%H%M%S"),
        source=source,
        quality=DataQuality.FRESH,
    )


class TencentQuoteSource:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def fetch(self, symbol: str) -> Quote:
        instrument = f"{market_prefix(symbol)}{symbol}"
        response = await self.client.get(f"https://qt.gtimg.cn/q={instrument}")
        response.raise_for_status()
        body = response.content.decode("gbk", errors="strict")
        if '="' not in body:
            raise ValueError("Tencent quote response has no payload")
        payload = body.split('="', 1)[1].rsplit('"', 1)[0]
        return parse_tencent_quote(payload, "tencent")
