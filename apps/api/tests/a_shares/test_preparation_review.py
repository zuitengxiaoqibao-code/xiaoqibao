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


class SymbolNews(News):
    def __init__(self, *, fail_symbol_once=False):
        super().__init__()
        self.symbol_calls = []
        self.fail_symbol_once = fail_symbol_once

    async def sync_symbol(self, symbol):
        self.symbol_calls.append(symbol)
        if self.fail_symbol_once:
            self.fail_symbol_once = False
            raise TimeoutError("symbol news offline")
        return {"events": 1}


class NewsRepo:
    def __init__(self, events_by_symbol=None):
        self.queries = []
        self.events_by_symbol = events_by_symbol or {}

    def effective_events_for_symbol(self, symbol, *, cutoff=None):
        self.queries.append((symbol, cutoff))
        return self.events_by_symbol.get(symbol, [])

    def events_for_symbol(self, symbol, *, cutoff=None):
        raise AssertionError("preparation must use effective symbol events")

    def events(self):
        raise AssertionError("preparation must use the bounded symbol query")


class Classification:
    def __init__(self, *, fail_once=False):
        self.calls = []
        self.fail_once = fail_once

    async def sync_symbol(self, symbol):
        self.calls.append(symbol)
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError("classification offline")
        return type("Snapshot", (), {"classification_id": "classification-1"})()


class FundFlow:
    def __init__(self, *, fail_once=False):
        self.calls = []
        self.fail_once = fail_once

    async def sync_symbol(self, symbol):
        self.calls.append(symbol)
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError("fund flow offline")
        return type("Snapshot", (), {"snapshot_id": "fund-flow-1"})()


class LatestSnapshotRepository:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.calls = []

    def latest(self, symbol, as_of, *, cutoff=None):
        self.calls.append((symbol, as_of, cutoff))
        return self.snapshot


class Calendar:
    def is_trading_day(self, value):
        return value.weekday() < 5

    def previous_trading_day(self, value):
        value -= timedelta(days=1)
        while value.weekday() >= 5:
            value -= timedelta(days=1)
        return value


def subject(
    tmp_path, *, bars=None, history=None, news=None, clock=None,
    calendar=None, news_repository=None, lock_timeout_seconds=1.0,
    classification=None, fund_flow=None,
):
    bars = bars or Bars()
    return AStockPreparationService(
        bars,
        history or History(bars),
        Diagnosis(),
        news or News(),
        news_repository or NewsRepo(),
        calendar or Calendar(),
        classification_service=classification,
        fund_flow_service=fund_flow,
        lock_dir=tmp_path,
        clock=clock or (lambda: datetime(2026, 7, 18, 3, tzinfo=UTC)),
        news_cooldown_seconds=300,
        fund_flow_cooldown_seconds=300,
        lock_timeout_seconds=lock_timeout_seconds,
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
async def test_symbol_news_uses_independent_per_stock_cooldown(tmp_path):
    bars = Bars(latest=FRIDAY)
    news = SymbolNews()
    service = subject(tmp_path, bars=bars, news=news)

    await service.prepare("600519", as_of=FRIDAY)
    await service.prepare("600000", as_of=FRIDAY)
    await service.prepare("600519", as_of=FRIDAY)

    assert news.calls == 1
    assert news.symbol_calls == ["600519", "600000"]


@pytest.mark.asyncio
async def test_symbol_news_failure_is_retried_without_repeating_fresh_global_sync(tmp_path):
    bars = Bars(latest=FRIDAY)
    news = SymbolNews(fail_symbol_once=True)
    service = subject(tmp_path, bars=bars, news=news)

    first = await service.prepare("600519", as_of=FRIDAY)
    second = await service.prepare("600519", as_of=FRIDAY)

    assert first.status == "partial"
    assert second.refreshed is True
    assert news.calls == 1
    assert news.symbol_calls == ["600519", "600519"]


@pytest.mark.asyncio
async def test_classification_uses_independent_daily_symbol_cooldown(tmp_path):
    classification = Classification()
    service = subject(tmp_path, classification=classification)

    await service.prepare("600519", as_of=FRIDAY)
    await service.prepare("600000", as_of=FRIDAY)
    await service.prepare("600519", as_of=FRIDAY)

    assert classification.calls == ["600519", "600000"]


@pytest.mark.asyncio
async def test_classification_failure_retries_without_repeating_fresh_news(tmp_path):
    news = SymbolNews()
    classification = Classification(fail_once=True)
    service = subject(
        tmp_path, news=news, classification=classification
    )

    first = await service.prepare("600519", as_of=FRIDAY)
    second = await service.prepare("600519", as_of=FRIDAY)

    assert first.refreshed is True
    assert second.refreshed is True
    assert news.calls == 1
    assert news.symbol_calls == ["600519"]
    assert classification.calls == ["600519", "600519"]


@pytest.mark.asyncio
async def test_fund_flow_uses_independent_per_stock_cooldown(tmp_path):
    fund_flow = FundFlow()
    service = subject(tmp_path, fund_flow=fund_flow)

    await service.prepare("600519", as_of=FRIDAY)
    await service.prepare("600000", as_of=FRIDAY)
    await service.prepare("600519", as_of=FRIDAY)

    assert fund_flow.calls == ["600519", "600000"]


@pytest.mark.asyncio
async def test_fund_flow_failure_retries_without_degrading_core_status(tmp_path):
    fund_flow = FundFlow(fail_once=True)
    service = subject(tmp_path, fund_flow=fund_flow)

    first = await service.prepare("600519", as_of=FRIDAY)
    second = await service.prepare("600519", as_of=FRIDAY)

    assert first.status == "partial"
    assert second.status == "partial"
    assert second.refreshed is True
    assert fund_flow.calls == ["600519", "600519"]


@pytest.mark.asyncio
async def test_auxiliary_failures_are_reported_and_successful_retry_clears_reason(tmp_path):
    classification = Classification(fail_once=True)
    fund_flow = FundFlow(fail_once=True)
    service = subject(
        tmp_path, classification=classification, fund_flow=fund_flow
    )

    first = await service.prepare("600519", as_of=FRIDAY)
    first_sources = {item.name: item for item in first.sources}
    assert first_sources["classification"].status == "partial"
    assert first_sources["classification"].reason == "classification offline"
    assert first_sources["fund_flow"].status == "partial"
    assert first_sources["fund_flow"].reason == "fund flow offline"

    second = await service.prepare("600519", as_of=FRIDAY)
    second_sources = {item.name: item for item in second.sources}
    assert second_sources["classification"].status == "ready"
    assert second_sources["classification"].reason is None
    assert second_sources["fund_flow"].status == "ready"
    assert second_sources["fund_flow"].reason is None


@pytest.mark.asyncio
async def test_auxiliary_sources_show_last_verified_repository_timestamp(tmp_path):
    observed = datetime(2026, 7, 17, 7, 30, tzinfo=UTC)
    classification = Classification()
    classification.repository = LatestSnapshotRepository(
        type("Snapshot", (), {"observed_at": observed})()
    )
    fund_flow = FundFlow()
    fund_flow.repository = LatestSnapshotRepository(
        type("Snapshot", (), {"observed_at": observed})()
    )
    service = subject(
        tmp_path, classification=classification, fund_flow=fund_flow
    )

    result = await service.inspect("600519", as_of=FRIDAY)
    sources = {item.name: item for item in result.sources}
    assert sources["classification"].status == "ready"
    assert sources["classification"].observed_at == observed
    assert sources["fund_flow"].status == "ready"
    assert sources["fund_flow"].observed_at == observed
    assert classification.repository.calls == [("600519", FRIDAY, None)]
    assert fund_flow.repository.calls == [("600519", FRIDAY, None)]


@pytest.mark.asyncio
async def test_partial_refresh_is_not_cached_and_retries(tmp_path):
    bars = Bars(latest=date(2026, 7, 16), count=59)
    history = History(bars, fail_once=True)
    news = News(fail_once=True)
    service = subject(tmp_path, bars=bars, history=history, news=news)

    first = await service.prepare("600519", as_of=FRIDAY)
    second = await service.prepare("600519", as_of=FRIDAY)

    assert first.status == "partial"
    assert first.refreshed is False
    assert second.status == "partial"
    assert second.refreshed is True
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


class LinkedEvent:
    def __init__(self, observed_at):
        self.normalized_at = observed_at


@pytest.mark.asyncio
async def test_fresh_global_news_without_verified_symbol_event_is_partial(tmp_path):
    service = subject(tmp_path)
    service._write_news_marker(service._global_news_marker(), service._now())

    result = await service.inspect("600519", as_of=SATURDAY)

    news = next(item for item in result.sources if item.name == "news")
    assert news.status == "partial"
    assert news.reason == "news_no_verified_symbol_events"
    assert news.observed_at is None


@pytest.mark.asyncio
async def test_unrelated_verified_news_does_not_make_symbol_ready(tmp_path):
    repository = NewsRepo({"600000": [LinkedEvent(datetime(2026, 7, 18, 2, tzinfo=UTC))]})
    service = subject(tmp_path, news_repository=repository)
    service._write_news_marker(service._global_news_marker(), service._now())

    result = await service.inspect("600519", as_of=SATURDAY)

    news = next(item for item in result.sources if item.name == "news")
    assert news.status == "partial"
    assert news.reason == "news_no_verified_symbol_events"


@pytest.mark.asyncio
async def test_linked_verified_news_makes_symbol_ready(tmp_path):
    observed = datetime(2026, 7, 18, 2, tzinfo=UTC)
    service = subject(
        tmp_path, news_repository=NewsRepo({"600519": [LinkedEvent(observed)]})
    )
    service._write_news_marker(service._global_news_marker(), service._now())

    result = await service.inspect("600519", as_of=SATURDAY)

    news = next(item for item in result.sources if item.name == "news")
    assert news.status == "ready"
    assert news.reason is None
    assert news.observed_at == observed


@pytest.mark.asyncio
async def test_successful_history_write_with_news_failure_is_refreshed(tmp_path):
    bars = Bars(latest=date(2026, 7, 16), count=59)
    result = await subject(
        tmp_path, bars=bars, news=News(fail_once=True)
    ).prepare("600519", as_of=FRIDAY)

    assert result.status == "partial"
    assert result.refreshed is True


@pytest.mark.asyncio
async def test_successful_news_write_with_history_failure_is_refreshed(tmp_path):
    bars = Bars(latest=date(2026, 7, 16), count=59)
    result = await subject(
        tmp_path, bars=bars, history=History(bars, fail_once=True)
    ).prepare("600519", as_of=FRIDAY)

    assert result.status == "partial"
    assert result.refreshed is True


@pytest.mark.asyncio
async def test_cancelled_lock_wait_releases_after_background_acquisition(tmp_path):
    holder = subject(tmp_path, lock_timeout_seconds=1)
    waiter = subject(tmp_path, lock_timeout_seconds=1)
    third = subject(tmp_path, lock_timeout_seconds=1)

    async def wait_for_lock():
        async with waiter._file_lock("cancel.lock"):
            pass

    async with holder._file_lock("cancel.lock"):
        task = asyncio.create_task(wait_for_lock())
        await asyncio.sleep(0.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await asyncio.sleep(0.08)

    async with third._file_lock("cancel.lock"):
        assert third._active_locks == 1


@pytest.mark.asyncio
async def test_lock_contention_timeout_degrades_to_partial(tmp_path):
    holder = subject(tmp_path, lock_timeout_seconds=1)
    contender = subject(tmp_path, lock_timeout_seconds=0.04)

    async with holder._file_lock("history-600519.lock"):
        result = await contender.prepare("600519", as_of=FRIDAY)

    history = next(item for item in result.sources if item.name == "history")
    assert result.status == "partial"
    assert result.refreshed is True
    assert history.reason == "preparation lock timed out: history-600519.lock"


@pytest.mark.asyncio
async def test_lock_retries_nonblocking_until_holder_releases(tmp_path):
    holder = subject(tmp_path, lock_timeout_seconds=1)
    waiter = subject(tmp_path, lock_timeout_seconds=0.5)

    async def release_soon():
        async with holder._file_lock("retry.lock"):
            await asyncio.sleep(0.06)

    owner = asyncio.create_task(release_soon())
    await asyncio.sleep(0.01)
    async with waiter._file_lock("retry.lock"):
        assert waiter._active_locks == 1
    await owner


class BlockingCalendar(Calendar):
    def is_trading_day(self, value):
        time.sleep(0.2)
        return super().is_trading_day(value)


@pytest.mark.asyncio
async def test_inspect_calendar_does_not_block_event_loop(tmp_path):
    service = subject(tmp_path, calendar=BlockingCalendar())
    ticked = asyncio.Event()

    async def ticker():
        await asyncio.sleep(0.01)
        ticked.set()

    inspection = asyncio.create_task(service.inspect("600519", as_of=SATURDAY))
    tick = asyncio.create_task(ticker())
    await asyncio.wait_for(ticked.wait(), timeout=0.1)
    await asyncio.gather(inspection, tick)


def test_news_marker_publication_is_atomic(tmp_path, monkeypatch):
    service = subject(tmp_path)
    marker = service._global_news_marker()
    marker.write_text("2026-07-18T02:59:00+00:00", encoding="utf-8")
    observed = []
    real_replace = __import__("os").replace

    def inspect_before_replace(source, destination):
        observed.append(marker.read_text(encoding="utf-8"))
        real_replace(source, destination)

    monkeypatch.setattr("qibao_api.a_shares.preparation.os.replace", inspect_before_replace)
    service._write_news_marker(marker, datetime(2026, 7, 18, 3, tzinfo=UTC))

    assert observed == ["2026-07-18T02:59:00+00:00"]
    assert marker.read_text(encoding="utf-8") == "2026-07-18T03:00:00+00:00"
