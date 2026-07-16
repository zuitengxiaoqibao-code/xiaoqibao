from datetime import UTC, datetime, timedelta

import pytest

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.news import NewsArticle
from qibao_api.gongbu.news_ingestion import NewsIngestionService
from qibao_api.gongbu.news_linking import DeterministicNewsLinker
from qibao_api.gongbu.news_repository import NewsRepository
from qibao_api.libu_compliance.repository import ComplianceRepository
from qibao_api.contracts.risk import ComplianceRecord
from qibao_api.zhongshu.news_ai import NewsAIGateway


NOW = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)


class Source:
    async def fetch(self):
        import hashlib

        raw = b"600000 policy news"
        return [NewsArticle(
            article_id="news-1", canonical_url="https://news.example/1",
            publisher="测试来源", title="600000获得支持政策",
            summary="先进制造专项政策。", published_at=NOW, fetched_at=NOW,
            content_hash=hashlib.sha256(raw).hexdigest(), raw_snapshot=raw,
            source_verified=True,
        )]


class UnavailableProvider:
    async def complete(self, _request):
        raise OSError("model offline")


class RefetchedSource:
    def __init__(self) -> None:
        self.fetch_count = 0

    async def fetch(self):
        import hashlib

        self.fetch_count += 1
        raw = f"600000 policy news poll {self.fetch_count}".encode()
        return [NewsArticle(
            article_id="news-stable", canonical_url="https://news.example/stable",
            publisher="测试来源", title="600000获得支持政策",
            summary="先进制造专项政策。", published_at=NOW,
            fetched_at=NOW + timedelta(minutes=self.fetch_count),
            content_hash=hashlib.sha256(b"stable semantic content").hexdigest(),
            raw_snapshot=raw, source_verified=True,
        )]


class StockSource:
    def __init__(self, *, explicit: bool = True) -> None:
        self.symbols = []
        self.explicit = explicit

    async def fetch(self, symbol):
        import hashlib

        self.symbols.append(symbol)
        raw = f"stock-news-{symbol}-{self.explicit}".encode()
        summary = f"{symbol} 公司发布公告" if self.explicit else "搜索结果未提及该股票"
        return [NewsArticle(
            article_id=f"stock-{symbol}-{self.explicit}",
            canonical_url="https://finance.eastmoney.com/a/stock.html",
            publisher="测试来源", title="个股新闻", summary=summary,
            published_at=NOW, fetched_at=NOW,
            content_hash=hashlib.sha256(raw).hexdigest(), raw_snapshot=raw,
            source_verified=True,
        )]


def authorize(repository: ComplianceRepository) -> None:
    repository.append_record(ComplianceRecord(
        record_id="news-eastmoney", asset=AssetKind.A_SHARE, source="eastmoney",
        permission_state="authorized", permission_reference="test",
        disclaimer_version="2026-07", user_acknowledged_at=NOW, recorded_at=NOW,
    ))


@pytest.mark.asyncio
async def test_ingestion_requires_authorization_and_persists_complete_chain(tmp_path) -> None:
    compliance = ComplianceRepository(tmp_path / "compliance.sqlite3")
    compliance.set_feature_sources("market_news", AssetKind.A_SHARE, ("eastmoney",))
    repository = NewsRepository(tmp_path / "news.sqlite3")
    service = NewsIngestionService(
        Source(), repository,
        DeterministicNewsLinker(
            instrument_aliases={},
            industry_keywords={"高端制造": ("先进制造",)},
            theme_keywords={"政策支持": ("支持政策", "专项政策")},
        ),
        compliance,
        NewsAIGateway(
            UnavailableProvider(), provider_name="unconfigured", model="none",
            prompt_version="news-v1", clock=lambda: NOW,
        ),
    )

    with pytest.raises(Exception, match="eastmoney"):
        await service.sync()

    authorize(compliance)
    result = await service.sync()

    assert result == {
        "fetched": 1, "inserted": 1, "clusters": 1, "events": 1,
        "interpretations": 1,
    }
    assert repository.articles()[0].article_id == "news-1"
    assert repository.events()[0].affected_instruments == (
        (AssetKind.A_SHARE, "600000"),
    )
    assert repository.interpretations()[0].degraded is True
    assert (await service.sync())["inserted"] == 0
    assert len(repository.interpretations()) == 1
    repository.close()
    compliance.close()


@pytest.mark.asyncio
async def test_ingestion_reuses_the_first_snapshot_for_a_refetched_article(tmp_path) -> None:
    compliance = ComplianceRepository(tmp_path / "compliance.sqlite3")
    compliance.set_feature_sources("market_news", AssetKind.A_SHARE, ("eastmoney",))
    authorize(compliance)
    repository = NewsRepository(tmp_path / "news.sqlite3")
    service = NewsIngestionService(
        RefetchedSource(),
        repository,
        DeterministicNewsLinker(
            instrument_aliases={}, industry_keywords={}, theme_keywords={}
        ),
        compliance,
    )

    first = await service.sync()
    second = await service.sync()

    assert first["events"] == 1
    assert second["inserted"] == 0
    assert second["events"] == 0
    assert repository.articles()[0].raw_snapshot == b"600000 policy news poll 1"
    assert repository.events()[0].normalized_at == NOW + timedelta(minutes=1)
    repository.close()
    compliance.close()


@pytest.mark.asyncio
async def test_ingestion_records_taxonomy_rule_changes_as_an_idempotent_correction(
    tmp_path,
) -> None:
    compliance = ComplianceRepository(tmp_path / "compliance.sqlite3")
    compliance.set_feature_sources("market_news", AssetKind.A_SHARE, ("eastmoney",))
    authorize(compliance)
    repository = NewsRepository(tmp_path / "news.sqlite3")
    source = Source()
    legacy = NewsIngestionService(
        source,
        repository,
        DeterministicNewsLinker(
            instrument_aliases={},
            industry_keywords={"legacy-industry": ("先进制造",)},
            theme_keywords={},
        ),
        compliance,
    )
    current = NewsIngestionService(
        source,
        repository,
        DeterministicNewsLinker(
            instrument_aliases={}, industry_keywords={}, theme_keywords={}
        ),
        compliance,
    )

    await legacy.sync()
    second = await current.sync()
    third = await current.sync()

    assert second["events"] == 0
    assert third["events"] == 0
    assert repository.events()[0].industries == ("legacy-industry",)
    assert repository.effective_events()[0].industries == ()
    assert len(repository.corrections()) == 1
    assert repository.corrections()[0].origin == "system"
    repository.close()
    compliance.close()


@pytest.mark.asyncio
async def test_symbol_ingestion_requires_explicit_article_link_before_verification(tmp_path) -> None:
    compliance = ComplianceRepository(tmp_path / "compliance.sqlite3")
    compliance.set_feature_sources("market_news", AssetKind.A_SHARE, ("eastmoney",))
    authorize(compliance)
    repository = NewsRepository(tmp_path / "news.sqlite3")
    explicit = StockSource()
    unrelated = StockSource(explicit=False)
    linker = DeterministicNewsLinker(
        instrument_aliases={}, industry_keywords={}, theme_keywords={}
    )
    service = NewsIngestionService(
        Source(), repository, linker, compliance, stock_source=explicit
    )

    result = await service.sync_symbol("600519")
    other = NewsIngestionService(
        Source(), repository, linker, compliance, stock_source=unrelated
    )
    await other.sync_symbol("000001")

    assert result["fetched"] == 1
    assert explicit.symbols == ["600519"]
    assert repository.events_for_symbol("600519")[0].review_state == "verified"
    unrelated_event = next(
        item for item in repository.events() if item.event_id.startswith("event-stock-000001")
    )
    assert unrelated_event.affected_instruments == ()
    assert unrelated_event.review_state == "pending"
    repository.close()
    compliance.close()
