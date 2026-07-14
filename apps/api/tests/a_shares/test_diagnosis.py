from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from qibao_api.a_shares.diagnosis import AShareDiagnosisService
from qibao_api.contracts.bars import DailyBar
from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.news import EvidenceCitation, NormalizedNewsEvent
from qibao_api.gongbu.tencent_quotes import TencentMarketSnapshot


AS_OF = date(2026, 7, 14)
OBSERVED_AT = datetime(2026, 7, 14, 10, 30)


def bars(symbol: str = "600000", count: int = 80) -> list[DailyBar]:
    result = []
    for index in range(count):
        close = Decimal("10") + Decimal(index) / Decimal("100")
        result.append(DailyBar(
            symbol=symbol, trade_date=date(2026, 4, 1) + timedelta(days=index),
            open=close, high=close + Decimal("0.1"), low=close - Decimal("0.1"),
            close=close, volume=2_000_000 + index * 100,
            amount=close * Decimal(2_000_000 + index * 100), source="mootdx",
        ))
    return result


class FakeBars:
    def __init__(self, values: dict[str, list[DailyBar]]) -> None:
        self.values = values

    def symbols_with_history(self, minimum_bars: int, as_of: date) -> list[str]:
        return sorted(symbol for symbol, values in self.values.items() if len(values) >= minimum_bars)

    def latest_many(self, symbols: list[str], limit: int, as_of: date):
        return {symbol: self.values.get(symbol, [])[-limit:] for symbol in symbols}


class FakeMarket:
    async def fetch_snapshot(self, symbol: str) -> TencentMarketSnapshot:
        return TencentMarketSnapshot(
            symbol=symbol, name="浦发银行", price=Decimal("10.25"),
            previous_close=Decimal("10.10"), observed_at=OBSERVED_AT,
            turnover_rate=Decimal("0.42"), pe_ttm=Decimal("6.32"),
            market_cap_yi=Decimal("3120.50"), pb=Decimal("0.58"), source="tencent",
        )


class FailingFinance:
    def fetch(self, symbol: str):
        raise RuntimeError("finance unavailable")


class EmptyNews:
    def events(self):
        return []


class NewsWithOtherAsset:
    def events(self):
        citation = EvidenceCitation(
            citation_id="citation-1", article_id="article-1",
            canonical_url="https://example.com/news", publisher="测试来源",
            published_at=datetime(2026, 7, 14, 8, tzinfo=UTC),
            quoted_text="行业需求变化", content_hash="a" * 64,
        )
        common = {
            "event_type": "industry_policy", "headline": "行业政策更新",
            "occurred_at": datetime(2026, 7, 14, 8, tzinfo=UTC),
            "normalized_at": datetime(2026, 7, 14, 9, tzinfo=UTC),
            "industries": ("银行",), "themes": (), "citations": (citation,),
            "association_confidence": Decimal("0.9"), "review_state": "verified",
        }
        return [
            NormalizedNewsEvent(
                event_id="event-target", affected_instruments=((AssetKind.A_SHARE, "600000"),),
                **common,
            ),
            NormalizedNewsEvent(
                event_id="event-other", affected_instruments=((AssetKind.A_SHARE, "000001"),),
                **common,
            ),
        ]


class FutureNews:
    def events(self):
        citation = EvidenceCitation(
            citation_id="citation-future", article_id="article-future",
            canonical_url="https://example.com/future", publisher="测试来源",
            published_at=datetime(2026, 7, 15, 8, tzinfo=UTC),
            quoted_text="未来事件", content_hash="b" * 64,
        )
        return [NormalizedNewsEvent(
            event_id="event-future", event_type="future_event", headline="未来事件",
            occurred_at=datetime(2026, 7, 15, 8, tzinfo=UTC),
            normalized_at=datetime(2026, 7, 15, 9, tzinfo=UTC),
            affected_instruments=((AssetKind.A_SHARE, "600000"),),
            citations=(citation,), association_confidence=Decimal("0.9"),
            review_state="verified",
        )]


class FutureMarket(FakeMarket):
    async def fetch_snapshot(self, symbol: str) -> TencentMarketSnapshot:
        current = await super().fetch_snapshot(symbol)
        return current.model_copy(update={"observed_at": datetime(2026, 7, 15, 10, 30)})


class WrongSymbolMarket(FakeMarket):
    async def fetch_snapshot(self, symbol: str) -> TencentMarketSnapshot:
        current = await super().fetch_snapshot(symbol)
        return current.model_copy(update={"symbol": "000001"})


@pytest.mark.asyncio
async def test_diagnosis_keeps_local_analysis_when_fundamentals_fail() -> None:
    service = AShareDiagnosisService(
        bar_repository=FakeBars({"600000": bars()}), market_source=FakeMarket(),
        finance_source=FailingFinance(), news_repository=EmptyNews(),
    )

    result = await service.diagnose("600000", AS_OF)

    assert result.sections["trend"].status == "ready"
    assert result.sections["fundamentals"].status == "unavailable"
    assert result.overall_status == "partial"
    assert "fundamentals" in result.missing_data
    assert result.action == "observe"


@pytest.mark.asyncio
async def test_diagnosis_only_uses_frozen_events_linked_to_symbol() -> None:
    service = AShareDiagnosisService(
        bar_repository=FakeBars({"600000": bars()}), market_source=FakeMarket(),
        finance_source=FailingFinance(), news_repository=NewsWithOtherAsset(),
    )

    result = await service.diagnose("600000", AS_OF)

    assert result.sections["events"].evidence_ids == ("event-target",)
    assert result.sections["events"].metrics["event_count"] == 1
    assert result.sections["industry"].metrics["industries"] == "银行"


def test_candidates_use_only_local_symbols_with_enough_history() -> None:
    service = AShareDiagnosisService(
        bar_repository=FakeBars({"600000": bars(), "000001": bars(count=40)}),
        market_source=FakeMarket(), finance_source=FailingFinance(),
        news_repository=EmptyNews(),
    )

    board = service.candidates(AS_OF, limit=20)

    assert [item.symbol for item in board.short_term] == ["600000"]
    assert [item.symbol for item in board.swing] == ["600000"]
    assert board.as_of == AS_OF


@pytest.mark.asyncio
async def test_historical_diagnosis_rejects_future_market_and_news() -> None:
    service = AShareDiagnosisService(
        bar_repository=FakeBars({"600000": bars()}), market_source=FutureMarket(),
        finance_source=FailingFinance(), news_repository=FutureNews(),
    )

    result = await service.diagnose("600000", AS_OF)

    assert result.sections["market"].status == "unavailable"
    assert result.sections["events"].metrics["event_count"] == 0
    assert "event-future" not in result.sections["events"].evidence_ids


def test_candidates_expose_invalid_history_without_failing_other_symbols() -> None:
    mixed = bars("000001")
    mixed[-1] = mixed[-1].model_copy(update={"source": "baidu"})
    service = AShareDiagnosisService(
        bar_repository=FakeBars({"600000": bars(), "000001": mixed}),
        market_source=FakeMarket(), finance_source=FailingFinance(),
        news_repository=EmptyNews(),
    )

    board = service.candidates(AS_OF, limit=20)

    assert [item.symbol for item in board.short_term] == ["600000"]
    assert board.exclusions[0].symbol == "000001"
    assert board.exclusions[0].reason_code == "invalid_history"


@pytest.mark.asyncio
async def test_zero_volume_history_does_not_abort_other_diagnosis_sections() -> None:
    zero_volume = [
        bar.model_copy(update={"volume": 0, "amount": Decimal("0")})
        for bar in bars()
    ]
    service = AShareDiagnosisService(
        bar_repository=FakeBars({"600000": zero_volume}), market_source=FakeMarket(),
        finance_source=FailingFinance(), news_repository=EmptyNews(),
    )

    result = await service.diagnose("600000", AS_OF)

    assert result.sections["market"].status == "ready"
    assert result.sections["trend"].status == "ready"
    assert result.sections["price_volume"].status == "ready"
    assert result.sections["price_volume"].metrics["volume_ratio"] is None


@pytest.mark.asyncio
async def test_market_snapshot_must_match_requested_symbol() -> None:
    service = AShareDiagnosisService(
        bar_repository=FakeBars({"600000": bars()}), market_source=WrongSymbolMarket(),
        finance_source=FailingFinance(), news_repository=EmptyNews(),
    )

    result = await service.diagnose("600000", AS_OF)

    assert result.sections["market"].status == "unavailable"
    assert result.sections["valuation"].status == "unavailable"


@pytest.mark.asyncio
async def test_price_volume_sorts_and_validates_repository_bars() -> None:
    descending = list(reversed(bars()))
    service = AShareDiagnosisService(
        bar_repository=FakeBars({"600000": descending}), market_source=FakeMarket(),
        finance_source=FailingFinance(), news_repository=EmptyNews(),
    )

    result = await service.diagnose("600000", AS_OF)

    assert result.sections["price_volume"].metrics["close"] == bars()[-1].close
    assert result.sections["trend"].status == "ready"
