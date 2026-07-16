from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field

from qibao_api.contracts.market import AssetKind, DataQuality, Quote
from qibao_api.contracts.instruments import AShareCode


class TencentMarketSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: AShareCode
    name: str
    price: Decimal = Field(gt=0)
    previous_close: Decimal = Field(gt=0)
    volume: Decimal | None = Field(default=None, ge=0)
    observed_at: datetime
    turnover_rate: Decimal | None = Field(default=None, ge=0)
    pe_ttm: Decimal | None = None
    market_cap_yi: Decimal | None = Field(default=None, ge=0)
    pb: Decimal | None = None
    source: str


def market_prefix(symbol: str) -> str:
    if symbol.startswith(("4", "8", "920")):
        return "bj"
    return "sh" if symbol.startswith(("5", "6")) else "sz"


def _optional_decimal(value: str) -> Decimal | None:
    return None if not value or value == "--" else Decimal(value)


def parse_tencent_snapshot(payload: str, source: str) -> TencentMarketSnapshot:
    fields = payload.split("~")
    if len(fields) < 47:
        raise ValueError("Tencent quote payload is incomplete")
    return TencentMarketSnapshot(
        symbol=fields[2],
        name=fields[1],
        price=Decimal(fields[3]),
        previous_close=Decimal(fields[4]),
        volume=_optional_decimal(fields[6]),
        observed_at=datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(
            tzinfo=ZoneInfo("Asia/Shanghai")
        ),
        turnover_rate=_optional_decimal(fields[38]),
        pe_ttm=_optional_decimal(fields[39]),
        market_cap_yi=_optional_decimal(fields[44]),
        pb=_optional_decimal(fields[46]),
        source=source,
    )


def parse_tencent_quote(payload: str, source: str) -> Quote:
    snapshot = parse_tencent_snapshot(payload, source)
    return Quote(
        symbol=snapshot.symbol,
        asset=AssetKind.A_SHARE,
        name=snapshot.name,
        price=snapshot.price,
        previous_close=snapshot.previous_close,
        observed_at=snapshot.observed_at,
        source=snapshot.source,
        quality=DataQuality.FRESH,
    )


class TencentQuoteSource:
    def __init__(
        self,
        client: httpx.AsyncClient,
        fallback_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.client = client
        self.fallback_client_factory = fallback_client_factory or (
            lambda: httpx.AsyncClient(timeout=10)
        )

    async def _request(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        response = await client.get(url)
        response.raise_for_status()
        return response

    async def _payload(self, symbol: str) -> str:
        instrument = f"{market_prefix(symbol)}{symbol}"
        url = f"https://qt.gtimg.cn/q={instrument}"
        try:
            response = await self._request(self.client, url)
        except httpx.TransportError:
            async with self.fallback_client_factory() as fallback_client:
                response = await self._request(fallback_client, url)
        body = response.content.decode("gbk", errors="strict")
        if '="' not in body:
            raise ValueError("Tencent quote response has no payload")
        return body.split('="', 1)[1].rsplit('"', 1)[0]

    async def fetch(self, symbol: str) -> Quote:
        return parse_tencent_quote(await self._payload(symbol), "tencent")

    async def fetch_snapshot(self, symbol: str) -> TencentMarketSnapshot:
        return parse_tencent_snapshot(await self._payload(symbol), "tencent")
