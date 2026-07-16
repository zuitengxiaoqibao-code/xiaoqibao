import json
from datetime import UTC, datetime, timedelta

import pytest

from qibao_api.gongbu.news_collection import (
    EastmoneyGlobalNewsSource,
    NewsHttpResponse,
    deduplicate_articles,
)


NOW = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)


def payload(items: list[dict]) -> bytes:
    return json.dumps(
        {"data": {"fastNewsList": items}}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


@pytest.mark.asyncio
async def test_eastmoney_global_news_preserves_article_evidence() -> None:
    raw = payload([
        {
            "code": "202607140001",
            "title": "政策支持先进制造业发展",
            "summary": "有关部门发布支持政策。",
            "showTime": "2026-07-14 08:55:00",
            "url": "https://finance.eastmoney.com/a/202607140001.html",
        }
    ])

    async def transport(_url, _params, _headers):
        return NewsHttpResponse(200, raw)

    source = EastmoneyGlobalNewsSource(transport=transport, clock=lambda: NOW)
    articles = await source.fetch(page_size=20)

    assert len(articles) == 1
    assert articles[0].publisher == "东方财富"
    assert articles[0].summary == "有关部门发布支持政策。"
    assert articles[0].raw_snapshot
    assert articles[0].content_hash
    assert articles[0].source_verified is True
    assert articles[0].published_at.isoformat() == "2026-07-14T08:55:00+08:00"


@pytest.mark.asyncio
async def test_eastmoney_transient_counters_do_not_create_a_new_article_version() -> None:
    rows = [
        {
            "code": "202607163809246888",
            "title": "美国首次申请失业救济人数修正",
            "summary": "申请人数修正至21.6万。",
            "showTime": "2026-07-14 08:55:00",
            "realSort": "1784205269046888",
            "pinglun_Num": 1,
            "share": 1,
        },
        {
            "code": "202607163809246888",
            "title": "美国首次申请失业救济人数修正",
            "summary": "申请人数修正至21.6万。",
            "showTime": "2026-07-14 08:55:00",
            "realSort": "1784205269046888",
            "pinglun_Num": 12,
            "share": 3,
        },
    ]

    async def transport(_url, _params, _headers):
        return NewsHttpResponse(200, payload([rows.pop(0)]))

    source = EastmoneyGlobalNewsSource(
        transport=transport,
        clock=lambda: NOW,
        minimum_interval=0,
    )
    first = (await source.fetch())[0]
    second = (await source.fetch())[0]

    assert first.article_id == second.article_id
    assert first.content_hash == second.content_hash
    assert first.raw_snapshot != second.raw_snapshot
    assert first.article_id.startswith("202607163809246888-")
    assert json.loads(first.raw_snapshot)["pinglun_Num"] == 1
    assert json.loads(second.raw_snapshot)["pinglun_Num"] == 12


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("title", "美国首次申请失业救济人数再次修正"),
        ("summary", "申请人数再次修正至21.5万。"),
        ("showTime", "2026-07-14 08:56:00"),
        ("url", "https://finance.eastmoney.com/a/revised.html"),
    ],
)
async def test_eastmoney_evidence_changes_create_a_new_article_version(
    field: str,
    changed_value: str,
) -> None:
    original = {
        "code": "202607140001",
        "title": "政策支持先进制造业发展",
        "summary": "有关部门发布支持政策。",
        "showTime": "2026-07-14 08:55:00",
        "url": "https://finance.eastmoney.com/a/202607140001.html",
    }
    changed = {**original, field: changed_value}
    rows = [original, changed]

    async def transport(_url, _params, _headers):
        return NewsHttpResponse(200, payload([rows.pop(0)]))

    source = EastmoneyGlobalNewsSource(
        transport=transport,
        clock=lambda: NOW,
        minimum_interval=0,
    )
    first = (await source.fetch())[0]
    second = (await source.fetch())[0]

    assert first.article_id != second.article_id
    assert first.content_hash != second.content_hash
    assert first.article_id.startswith("202607140001-")
    assert second.article_id.startswith("202607140001-")


@pytest.mark.asyncio
async def test_eastmoney_article_without_provider_code_uses_semantic_hash_id() -> None:
    rows = [
        {
            "title": "政策支持先进制造业发展",
            "summary": "有关部门发布支持政策。",
            "showTime": "2026-07-14 08:55:00",
            "pinglun_Num": 1,
        },
        {
            "title": "政策支持先进制造业发展",
            "summary": "有关部门发布支持政策。",
            "showTime": "2026-07-14 08:55:00",
            "pinglun_Num": 9,
        },
    ]

    async def transport(_url, _params, _headers):
        return NewsHttpResponse(200, payload([rows.pop(0)]))

    source = EastmoneyGlobalNewsSource(
        transport=transport,
        clock=lambda: NOW,
        minimum_interval=0,
    )
    first = (await source.fetch())[0]
    second = (await source.fetch())[0]

    assert first.article_id == second.article_id == first.content_hash[:24]
    assert first.content_hash == second.content_hash
    assert first.raw_snapshot != second.raw_snapshot


@pytest.mark.asyncio
async def test_eastmoney_source_serializes_requests_and_retries_once() -> None:
    responses = [
        NewsHttpResponse(429, b"rate limited"),
        NewsHttpResponse(200, payload([])),
    ]
    monotonic_values = iter([0.0, 0.2, 1.3])
    sleeps: list[float] = []

    async def transport(_url, _params, _headers):
        return responses.pop(0)

    async def sleep(delay: float):
        sleeps.append(delay)

    source = EastmoneyGlobalNewsSource(
        transport=transport,
        clock=lambda: NOW,
        monotonic=lambda: next(monotonic_values),
        sleep=sleep,
        minimum_interval=1.0,
    )

    assert await source.fetch() == []
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_eastmoney_source_does_not_retry_permanent_parse_errors() -> None:
    calls = 0

    async def transport(_url, _params, _headers):
        nonlocal calls
        calls += 1
        return NewsHttpResponse(200, b"not-json")

    source = EastmoneyGlobalNewsSource(transport=transport, clock=lambda: NOW)

    with pytest.raises(ValueError, match="JSON"):
        await source.fetch()
    assert calls == 1


@pytest.mark.asyncio
async def test_eastmoney_source_retries_one_transient_network_error() -> None:
    calls = 0

    async def transport(_url, _params, _headers):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary disconnect")
        return NewsHttpResponse(200, payload([]))

    source = EastmoneyGlobalNewsSource(transport=transport, clock=lambda: NOW)

    assert await source.fetch() == []
    assert calls == 2


def test_deduplication_uses_url_hash_and_near_duplicate_title() -> None:
    from qibao_api.contracts.news import NewsArticle

    def item(article_id: str, url: str, title: str, content_hash: str) -> NewsArticle:
        return NewsArticle(
            article_id=article_id,
            canonical_url=url,
            publisher="测试来源",
            title=title,
            published_at=NOW,
            fetched_at=NOW + timedelta(seconds=1),
            content_hash=content_hash,
            raw_snapshot=article_id.encode(),
            source_verified=True,
        )

    articles = [
        item("1", "https://news.example/1", "政策支持先进制造业发展", "1" * 64),
        item("2", "https://news.example/1", "转载：政策支持先进制造业发展", "2" * 64),
        item("3", "https://news.example/3", "政策支持先进制造业发展！", "3" * 64),
        item("4", "https://news.example/4", "完全不同的市场新闻", "3" * 64),
    ]

    clusters = deduplicate_articles(articles)

    assert len(clusters) == 1
    assert clusters[0].article_ids == ("1", "2", "3", "4")
    assert clusters[0].source_urls == (
        "https://news.example/1",
        "https://news.example/3",
        "https://news.example/4",
    )
