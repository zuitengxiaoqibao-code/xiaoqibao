from decimal import Decimal

import httpx

from qibao_api.contracts.bars import DailyBar
from qibao_api.gongbu.tdx_history import DataSourceUnavailable

BAIDU_KLINE_URL = "https://finance.pae.baidu.com/selfselect/getstockquotation"


class BaiduHistorySource:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def fetch_daily(self, symbol: str, limit: int = 250) -> list[DailyBar]:
        response = self.client.get(
            BAIDU_KLINE_URL,
            params={
                "all": "1", "isIndex": "false", "isBk": "false", "isBlock": "false",
                "isFutures": "false", "isStock": "true", "newFormat": "1",
                "group": "quotation_kline_ab", "finClientType": "pc", "code": symbol,
                "start_time": "", "ktype": "1",
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/vnd.finance-web.v1+json",
                "Origin": "https://gushitong.baidu.com",
                "Referer": "https://gushitong.baidu.com/",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("ResultCode", -1)) != "0":
            raise DataSourceUnavailable("Baidu K-line source returned an error")
        market_data = payload.get("Result", {}).get("newMarketData", {})
        keys = market_data.get("keys") or []
        rows = [row for row in (market_data.get("marketData") or "").split(";") if row]
        bars = [self._parse_row(symbol, keys, row) for row in rows[-limit:]]
        if not bars:
            raise DataSourceUnavailable("Baidu K-line source returned no daily bars")
        return sorted(bars, key=lambda item: item.trade_date)

    @staticmethod
    def _parse_row(symbol: str, keys: list[str], row: str) -> DailyBar:
        values = row.split(",")
        data = dict(zip(keys, values, strict=False))
        return DailyBar(
            symbol=symbol,
            trade_date=data["time"],
            open=Decimal(data["open"]),
            high=Decimal(data["high"]),
            low=Decimal(data["low"]),
            close=Decimal(data["close"]),
            volume=int(Decimal(data["volume"])),
            amount=Decimal(data["amount"]),
            source="baidu",
        )

