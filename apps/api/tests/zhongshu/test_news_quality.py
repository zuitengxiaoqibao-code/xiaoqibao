from datetime import UTC, datetime
from decimal import Decimal

from qibao_api.contracts.news import (
    AIInterpretation,
    EvidenceCitation,
    InterpretationStatement,
    NewsCorrection,
)
from qibao_api.gongbu.news_collection import NewsCluster
from qibao_api.zhongshu.news_quality import NewsQualityService


NOW = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)


class Repository:
    def articles(self):
        return [object(), object(), object(), object()]

    def clusters(self):
        return [
            {"cluster": NewsCluster(primary_article_id="1", article_ids=("1", "2"), source_urls=("https://a", "https://b"))},
            {"cluster": NewsCluster(primary_article_id="3", article_ids=("3", "4"), source_urls=("https://c", "https://d"))},
        ]

    def events(self):
        return [type("Event", (), {"event_id": "event-1"})(), type("Event", (), {"event_id": "event-2"})()]

    def interpretations(self):
        citation = EvidenceCitation(
            citation_id="citation-1", article_id="article-1",
            canonical_url="https://news.example/1", publisher="测试来源",
            published_at=NOW, quoted_text="事实", content_hash="a" * 64,
        )
        return [AIInterpretation(
            interpretation_id="i1", event_id="event-1", generated_at=NOW,
            provider="cloud", model="m", prompt_version="v1", provider_attempts=4,
            invalid_output_count=1, provider_error_count=1,
            statements=(
                InterpretationStatement(statement_id="s1", kind="fact", text="事实", citation_ids=("citation-1",)),
                InterpretationStatement(statement_id="s2", kind="interpretation", text="解释"),
            ), citations=(citation,),
        )]

    def corrections(self):
        return [
            NewsCorrection(
                correction_id="c1", event_id="event-1", corrected_at=NOW,
                reason="人工复核行业归属", review_state="verified",
            ),
            NewsCorrection(
                correction_id="c2", event_id="event-2", corrected_at=NOW,
                reason="deterministic_linker_classification_update",
                origin="system", review_state="verified",
            ),
        ]


def test_quality_metrics_use_persisted_evidence_and_attempt_counts() -> None:
    metrics = NewsQualityService(Repository()).metrics()

    assert metrics.citation_coverage == Decimal("1.0000")
    assert metrics.duplicate_rate == Decimal("0.5000")
    assert metrics.invalid_json_rate == Decimal("0.2500")
    assert metrics.provider_error_rate == Decimal("0.2500")
    assert metrics.human_correction_rate == Decimal("0.5000")
    assert metrics.correction_count == 2
