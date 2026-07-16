import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from qibao_api.a_shares.preparation import AStockPreparationService


AS_OF = date(2026, 7, 16)
NOW = datetime(2026, 7, 16, 3, 0, tzinfo=timezone.utc)


class HistoryRepository:
    def __init__(self, bars=()) -> None:
        self.bars = list(bars)
        self.cutoffs = []

    def latest_many(self, symbols, limit, as_of, *, cutoff=None):
        self.cutoffs.append(cutoff)
        return {symbols[0]: [bar for bar in self.bars if bar.trade_date <= as_of][-limit:]}


class Bar:
    def __init__(self, trade_date) -> None:
        self.trade_date = trade_date


class HistoryService:
    def __init__(self, repository, *, fail=False, raises=False) -> None:
        self.repository = repository
        self.fail = fail
        self.raises = raises
        self.sync_calls = []

    def sync_symbol(self, symbol):
        self.sync_calls.append(symbol)
        if self.raises:
            raise TimeoutError("history timeout")
        if self.fail:
            return type("Report", (), {"state": "error", "message": "offline"})()
        self.repository.bars = [
            Bar(date(2026, 5, 18) + timedelta(days=offset)) for offset in range(60)
        ]
        self.repository.bars[-1].trade_date = AS_OF
        return type("Report", (), {"state": "ready", "message": "ok"})()


class Diagnosis:
    def __init__(self, *, quote_error=None, finance_error=None) -> None:
        self.quote_error = quote_error
        self.finance_error = finance_error
        self.calls = []

    async def _market(self, symbol, as_of, *, cutoff=None, degrade_authorization=False):
        self.calls.append(("quote", cutoff))
        return (
            None if self.quote_error else type("Quote", (), {"observed_at": NOW})(),
            self.quote_error,
        )

    async def _finance(self, symbol, as_of, *, cutoff=None, degrade_authorization=False):
        self.calls.append(("finance", cutoff))
        return (
            None if self.finance_error else type("Finance", (), {"observed_at": NOW})(),
            self.finance_error,
        )


class News:
    def __init__(self, *, fail=False) -> None:
        self.fail = fail
        self.calls = 0

    async def sync(self):
        self.calls += 1
        if self.fail:
            raise TimeoutError("news timeout")
        return {"events": 1}


class NewsRepository:
    def events(self):
        return [type("Event", (), {"normalized_at": NOW, "occurred_at": NOW})()]


class ScopedNewsRepository:
    def events(self):
        return [
            type("Event", (), {
                "normalized_at": NOW, "occurred_at": NOW,
                "affected_instruments": (("a_share", "600000"),),
                "review_state": "verified",
            })(),
            type("Event", (), {
                "normalized_at": NOW, "occurred_at": NOW,
                "affected_instruments": (("a_share", "600519"),),
                "review_state": "pending",
            })(),
        ]


def make_service(repository=None, history=None, diagnosis=None, news=None):
    repository = repository or HistoryRepository()
    return AStockPreparationService(
        repository,
        history or HistoryService(repository),
        diagnosis or Diagnosis(),
        news or News(),
        NewsRepository(),
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_prepare_syncs_missing_history_then_reassesses():
    repository = HistoryRepository()
    history = HistoryService(repository)
    result = await make_service(repository, history).prepare("600519", as_of=AS_OF)

    assert history.sync_calls == ["600519"]
    assert result.status in {"ready", "partial"}
    assert {item.name for item in result.sources} >= {"quote", "history", "finance", "news"}
    assert next(item for item in result.sources if item.name == "history").status == "ready"


@pytest.mark.asyncio
async def test_prepare_is_idempotent_for_same_evidence_version():
    repository = HistoryRepository()
    history = HistoryService(repository)
    service = make_service(repository, history)

    await service.prepare("600519", as_of=AS_OF)
    second = await service.prepare("600519", as_of=AS_OF)

    assert history.sync_calls == ["600519"]
    assert second.refreshed is False


@pytest.mark.asyncio
async def test_prepare_coalesces_concurrent_calls_for_same_key():
    repository = HistoryRepository()
    history = HistoryService(repository)
    service = make_service(repository, history)

    results = await asyncio.gather(*(
        service.prepare("600519", as_of=AS_OF) for _ in range(4)
    ))

    assert history.sync_calls == ["600519"]
    assert sum(result.refreshed for result in results) == 1


@pytest.mark.asyncio
async def test_prepare_returns_partial_sources_instead_of_raising():
    repository = HistoryRepository([Bar(AS_OF)] * 60)
    result = await make_service(
        repository,
        diagnosis=Diagnosis(quote_error="quote offline"),
        news=News(fail=True),
    ).prepare("600519", as_of=AS_OF)

    assert result.status == "partial"
    assert {item.name: item.status for item in result.sources} == {
        "quote": "partial", "history": "ready", "finance": "ready", "news": "partial"
    }


@pytest.mark.asyncio
async def test_prepare_degrades_unexpected_history_sync_failure():
    repository = HistoryRepository()
    result = await make_service(
        repository, history=HistoryService(repository, raises=True)
    ).prepare("600519", as_of=AS_OF)

    history = next(item for item in result.sources if item.name == "history")
    assert history.status == "partial"
    assert history.reason == "history timeout"


@pytest.mark.asyncio
async def test_historical_prepare_only_assesses_cutoff_evidence():
    cutoff = datetime(2026, 7, 14, 7, 0, tzinfo=timezone.utc)
    repository = HistoryRepository([Bar(date(2026, 7, 14))] * 60)
    history = HistoryService(repository)
    diagnosis = Diagnosis()
    news = News()

    await make_service(repository, history, diagnosis, news).prepare(
        "600519", as_of=date(2026, 7, 14), cutoff=cutoff
    )

    assert history.sync_calls == []
    assert news.calls == 0
    assert repository.cutoffs == [cutoff]
    assert diagnosis.calls == [("quote", cutoff), ("finance", cutoff)]


@pytest.mark.asyncio
async def test_prepare_news_observation_only_uses_verified_symbol_events():
    repository = HistoryRepository([Bar(AS_OF)] * 60)
    service = AStockPreparationService(
        repository, HistoryService(repository), Diagnosis(), News(),
        ScopedNewsRepository(), clock=lambda: NOW,
    )

    result = await service.prepare("600519", as_of=AS_OF)

    assert next(item for item in result.sources if item.name == "news").observed_at is None
