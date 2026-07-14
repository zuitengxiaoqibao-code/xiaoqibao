from datetime import UTC, datetime

import pytest

from qibao_api.contracts.news import NewsArticle
from qibao_api.gongbu.news_collection import NewsCluster
from qibao_api.gongbu.news_linking import DeterministicNewsLinker
from qibao_api.contracts.news import AIInterpretation, InterpretationStatement
from qibao_api.gongbu.news_repository import NewsIntegrityError, NewsRepository


NOW = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)


def article(article_id: str = "news-1", raw: bytes = b"raw-news-1") -> NewsArticle:
    import hashlib

    return NewsArticle(
        article_id=article_id,
        canonical_url=f"https://news.example/{article_id}",
        publisher="测试来源",
        title="先进制造政策发布",
        summary="政策明确支持先进制造产业。",
        published_at=NOW,
        fetched_at=NOW,
        content_hash=hashlib.sha256(raw).hexdigest(),
        raw_snapshot=raw,
        source_verified=True,
    )


def test_repository_persists_articles_and_clusters_append_only(tmp_path) -> None:
    repository = NewsRepository(tmp_path / "news.sqlite3")
    item = article()
    cluster = NewsCluster(
        primary_article_id=item.article_id,
        article_ids=(item.article_id,),
        source_urls=(item.canonical_url,),
    )

    assert repository.append_articles((item,)) == 1
    assert repository.append_articles((item,)) == 0
    cluster_id = repository.append_cluster(cluster)

    stored = repository.articles()
    assert stored == [item]
    assert repository.clusters()[0]["cluster_id"] == cluster_id
    assert repository.clusters()[0]["cluster"] == cluster
    event = DeterministicNewsLinker(
        instrument_aliases={}, industry_keywords={}, theme_keywords={}
    ).link(item)
    assert repository.append_event(event) is True
    assert repository.append_event(event) is False
    assert repository.events() == [event]
    interpretation = AIInterpretation(
        interpretation_id="interpretation-1", event_id=event.event_id,
        generated_at=NOW, provider="deterministic", model="evidence-summary-v1",
        prompt_version="news-v1", latency_ms=12, degraded=True,
        statements=(InterpretationStatement(
            statement_id="s1", kind="fact", text=item.title,
            citation_ids=(event.citations[0].citation_id,),
        ),), citations=event.citations,
    )
    assert repository.append_interpretation(interpretation) is True
    assert repository.append_interpretation(interpretation) is False
    assert repository.interpretations() == [interpretation]

    with pytest.raises(Exception, match="append-only"):
        repository.connection.execute(
            "UPDATE news_articles SET metadata='changed' WHERE article_id='news-1'"
        )
    repository.close()


def test_repository_rejects_provider_id_collision_and_tampering(tmp_path) -> None:
    repository = NewsRepository(tmp_path / "news.sqlite3")
    repository.append_articles((article(),))

    with pytest.raises(NewsIntegrityError, match="collision"):
        repository.append_articles((article(raw=b"different"),))

    repository.connection.execute("DROP TRIGGER reject_update_news_articles")
    repository.connection.execute(
        "UPDATE news_articles SET raw_snapshot=? WHERE article_id=?",
        (b"tampered", "news-1"),
    )
    with pytest.raises(NewsIntegrityError, match="integrity"):
        repository.articles()
    repository.close()
