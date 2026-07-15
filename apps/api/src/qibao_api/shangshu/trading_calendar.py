from datetime import date, datetime, timedelta
from typing import Protocol

import httpx


class TradingDaySignal(Protocol):
    def confirmed_date(self) -> date | None: ...


class TencentIndexTradingDaySignal:
    def __init__(
        self,
        client,
        *,
        clock=datetime.now,
        cache_seconds: int = 30,
    ) -> None:
        self.client = client
        self.clock = clock
        self.cache_duration = timedelta(seconds=cache_seconds)
        self._cached_at: datetime | None = None
        self._cached_date: date | None = None

    def confirmed_date(self) -> date | None:
        now = self.clock()
        if self._cached_at is not None and now - self._cached_at < self.cache_duration:
            return self._cached_date
        try:
            response = self.client.get("https://qt.gtimg.cn/q=sh000001")
            response.raise_for_status()
            body = response.content.decode("gbk", errors="strict")
            payload = body.split('="', 1)[1].rsplit('"', 1)[0]
            fields = payload.split("~")
            if len(fields) < 31 or not fields[3] or fields[3] == "0":
                raise ValueError("Tencent index payload is incomplete")
            observed = datetime.strptime(fields[30], "%Y%m%d%H%M%S").date()
        except (httpx.HTTPError, IndexError, UnicodeError, ValueError, OSError):
            observed = None
        self._cached_at = now
        self._cached_date = observed
        return observed


class StoredTradingCalendar:
    def __init__(self, bar_repository, live_signal: TradingDaySignal | None = None) -> None:
        self.bar_repository = bar_repository
        self.live_signal = live_signal

    def is_trading_day(self, value: date) -> bool:
        if value in self.bar_repository.trade_dates(limit=1000):
            return True
        return self.live_signal is not None and self.live_signal.confirmed_date() == value

    def previous_trading_day(self, value: date) -> date:
        candidates = [
            item for item in self.bar_repository.trade_dates(limit=1000) if item < value
        ]
        if not candidates:
            raise ValueError(f"no confirmed trading day exists before {value}")
        return max(candidates)
