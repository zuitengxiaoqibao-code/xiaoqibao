from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from qibao_api.contracts.news import NewsArticle
from qibao_api.gongbu.news_collection import NewsCluster
from qibao_api.gongbu.news_linking import DeterministicNewsLinker
from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.news import (
    AIInterpretation, InterpretationStatement, NewsCorrection, NormalizedNewsEvent,
)
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
    correction = NewsCorrection(
        correction_id="correction-1", event_id=event.event_id, corrected_at=NOW,
        reason="人工确认事件归属", review_state="verified",
        industries=("高端制造",),
    )
    assert repository.append_correction(correction) is True
    assert repository.append_correction(correction) is False
    assert repository.corrections() == [correction]

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


def test_repository_preserves_legacy_id_when_appending_a_versioned_article(tmp_path) -> None:
    repository = NewsRepository(tmp_path / "news.sqlite3")
    legacy = article(article_id="provider-1", raw=b"legacy raw snapshot")
    versioned = article(
        article_id="provider-1-a1b2c3d4e5f60718",
        raw=b"versioned raw snapshot",
    )

    repository.append_articles((legacy,))
    repository.append_articles((versioned,))

    assert repository.articles() == [legacy, versioned]
    repository.close()


def test_events_for_symbol_is_verified_linked_and_cutoff_bounded(tmp_path) -> None:
    repository = NewsRepository(tmp_path / "news.sqlite3")
    item = article()
    repository.append_articles((item,))
    base = DeterministicNewsLinker(
        instrument_aliases={}, industry_keywords={}, theme_keywords={}
    ).link(item)
    verified = base.model_copy(update={
        "event_id": "verified-600519",
        "affected_instruments": ((AssetKind.A_SHARE, "600519"),),
        "review_state": "verified",
    })
    pending = verified.model_copy(update={
        "event_id": "pending-600519", "review_state": "pending",
    })
    other = verified.model_copy(update={
        "event_id": "verified-600000",
        "affected_instruments": ((AssetKind.A_SHARE, "600000"),),
    })
    for event in (verified, pending, other):
        repository.append_event(NormalizedNewsEvent.model_validate(event))

    assert repository.events_for_symbol("600519", cutoff=NOW) == [verified]
    assert repository.events_for_symbol(
        "600519", cutoff=NOW - timedelta(microseconds=1)
    ) == []
    repository.close()


def test_reconcile_event_appends_one_system_correction_and_projects_effective_state(
    tmp_path,
) -> None:
    repository = NewsRepository(tmp_path / "news.sqlite3")
    item = article()
    repository.append_articles((item,))
    original = DeterministicNewsLinker(
        instrument_aliases={},
        industry_keywords={"legacy-industry": ("先进制造",)},
        theme_keywords={},
    ).link(item).model_copy(update={
        "affected_instruments": ((AssetKind.A_SHARE, "600519"),),
        "association_confidence": Decimal("1"),
        "review_state": "verified",
    })
    repository.append_event(NormalizedNewsEvent.model_validate(original))
    corrected = original.model_copy(update={
        "industries": (),
        "association_confidence": Decimal("1"),
    })

    assert repository.reconcile_event(corrected) == (False, True)
    assert repository.reconcile_event(corrected) == (False, False)
    assert repository.events() == [original]
    assert len(repository.corrections()) == 1
    correction = repository.corrections()[0]
    assert correction.origin == "system"
    assert repository.effective_events() == [corrected]
    assert repository.effective_events(
        cutoff=correction.corrected_at - timedelta(microseconds=1)
    ) == [original]
    assert repository.effective_events(cutoff=correction.corrected_at) == [corrected]
    assert repository.effective_events_for_symbol("600519", cutoff=NOW) == [original]
    assert repository.effective_events_for_symbol(
        "600519", cutoff=NOW - timedelta(microseconds=1)
    ) == []
    repository.close()


def test_reconcile_event_rejects_changes_to_frozen_evidence(tmp_path) -> None:
    repository = NewsRepository(tmp_path / "news.sqlite3")
    item = article()
    repository.append_articles((item,))
    original = DeterministicNewsLinker(
        instrument_aliases={}, industry_keywords={}, theme_keywords={}
    ).link(item)
    repository.append_event(original)

    with pytest.raises(NewsIntegrityError, match="collision"):
        repository.reconcile_event(original.model_copy(update={"headline": "changed"}))

    assert repository.corrections() == []
    repository.close()
