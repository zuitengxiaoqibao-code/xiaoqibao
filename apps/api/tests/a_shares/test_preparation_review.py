import asyncio
import time
from datetime import date, datetime, time as wall_time, timedelta, timezone

import pytest

from qibao_api.a_shares.preparation import AStockPreparationService


UTC = timezone.utc
FRIDAY = date(2026, 7, 17)
SATURDAY = date(2026, 7, 18)


class Bar:
    def __init__(self, trade_date, close="10"):
        self.trade_date = trade_date
        self.close = close


class Bars:
    def __init__(self, latest=FRIDAY, count=60):
        self.values = [Bar(latest - timedelta(days=count - index - 1)) for index in range(count)]

    def latest_many(self, symbols, limit, as_of, *, cutoff=None):
        return {symbols[0]: [item for item in self.values if item.trade_date <= as_of][-limit:]}


class History:
    def __init__(self, bars, *, fail_once=False):
        self.bars = bars
        self.calls = []
        self.fail_once = fail_once

    def sync_symbol(self, symbol):
        self.calls.append(symbol)
        time.sleep(0.03)
        if self.fail_once:
            self.fail_once = False
            return type("Report", (), {"state": "error", "message": "offline"})()
        self.bars.values = [Bar(FRIDAY - timedelta(days=59 - index)) for index in range(60)]
        return type("Report", (), {"state": "ready", "message": "ok"})()


class Diagnosis:
    def __init__(self):
        self.calls = []

    async def inspect_sources(self, symbol, as_of, *, cutoff=None):
        self.calls.append((symbol, as_of, cutoff))
        observed = datetime.combine(as_of, wall_time.min, tzinfo=UTC)
        return {
            "quote": (type("Value", (), {"observed_at": observed})(), None),
            "finance": (type("Value", (), {"observed_at": observed})(), None),
        }


class News:
    def __init__(self, *, fail_once=False):
        self.calls = 0
        self.fail_once = fail_once

    async def sync(self):
        self.calls += 1
        await asyncio.sleep(0.03)
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError("news offline")
        return {"events": 0}


class NewsRepo:
    def __init__(self):
        self.queries = []

    def events_for_symbol(self, symbol, *, cutoff=None):
        self.queries.append((symbol, cutoff))
        return []

    def events(self):
        raise AssertionError("preparation must use the bounded symbol query")


class Calendar:
    def is_trading_day(self, value):
        return value.weekday() < 5

    def previous_trading_day(self, value):
        value -= timedelta(days=1)
        while value.weekday() >= 5:
            value -= timedelta(days=1)
        return value


def subject(tmp_path, *, bars=None, history=None, news=None, clock=None):
    bars = bars or Bars()
    return AStockPreparationService(
        bars,
        history or History(bars),
        Diagnosis(),
        news or News(),
        NewsRepo(),
        Calendar(),
        lock_dir=tmp_path,
        clock=clock or (lambda: datetime(2026, 7, 18, 3, tzinfo=UTC)),
        news_cooldown_seconds=300,
    )


@pytest.mark.asyncio
async def test_inspect_is_read_only_and_rechecks_public_sources(tmp_path):
    bars = Bars(latest=FRIDAY)
    history = History(bars)
    news = News()
    service = subject(tmp_path, bars=bars, history=history, news=news)

    first = await service.inspect("600519", as_of=SATURDAY)
    second = await service.inspect("600519", as_of=SATURDAY)

    assert first.refreshed is False and second.refreshed is False
    assert history.calls == [] and news.calls == 0
    assert len(service.diagnosis_service.calls) == 2
    assert service._active_locks == 0


@pytest.mark.asyncio
async def test_two_instances_share_history_and_global_news_locks(tmp_path):
    bars = Bars(latest=date(2026, 7, 16), count=59)
    history = History(bars)
    news = News()
    one = subject(tmp_path, bars=bars, history=history, news=news)
    two = subject(tmp_path, bars=bars, history=history, news=news)

    results = await asyncio.gather(
        one.prepare("600519", as_of=FRIDAY),
        two.prepare("600519", as_of=FRIDAY),
    )

    assert history.calls == ["600519"]
    assert news.calls == 1
    assert sum(item.refreshed for item in results) == 1
    assert one._active_locks == two._active_locks == 0


@pytest.mark.asyncio
async def test_global_news_cooldown_is_shared_across_different_symbols(tmp_path):
    bars = Bars(latest=FRIDAY)
    news = News()
    one = subject(tmp_path, bars=bars, news=news)
    two = subject(tmp_path, bars=bars, news=news)

    await asyncio.gather(
        one.prepare("600519", as_of=FRIDAY),
        two.prepare("600000", as_of=FRIDAY),
    )

    assert news.calls == 1


@pytest.mark.asyncio
async def test_partial_refresh_is_not_cached_and_retries(tmp_path):
    bars = Bars(latest=date(2026, 7, 16), count=59)
    history = History(bars, fail_once=True)
    news = News(fail_once=True)
    service = subject(tmp_path, bars=bars, history=history, news=news)

    first = await service.prepare("600519", as_of=FRIDAY)
    second = await service.prepare("600519", as_of=FRIDAY)

    assert first.status == "partial"
    assert second.status == "ready"
    assert history.calls == ["600519", "600519"]
    assert news.calls == 2


@pytest.mark.asyncio
async def test_weekend_and_preclose_use_previous_confirmed_trading_day(tmp_path):
    weekend = subject(tmp_path / "weekend", bars=Bars(latest=FRIDAY))
    preclose_bars = Bars(latest=date(2026, 7, 16))
    preclose_history = History(preclose_bars)
    preclose = subject(
        tmp_path / "preclose", bars=preclose_bars, history=preclose_history,
        clock=lambda: datetime(2026, 7, 17, 3, tzinfo=UTC),
    )

    await weekend.prepare("600519", as_of=SATURDAY)
    await preclose.prepare("600519", as_of=FRIDAY)

    assert weekend.market_data_service.calls == []
    assert preclose_history.calls == []


@pytest.mark.asyncio
async def test_news_read_is_bounded_to_requested_symbol_and_cutoff(tmp_path):
    service = subject(tmp_path)
    cutoff = datetime(2026, 7, 17, 8, tzinfo=UTC)

    await service.inspect("600519", as_of=FRIDAY, cutoff=cutoff)

    assert service.news_repository.queries == [("600519", cutoff)]
