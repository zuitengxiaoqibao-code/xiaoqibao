from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.news import (
    AIInterpretation,
    EvidenceCitation,
    InterpretationStatement,
    NewsArticle,
    NormalizedNewsEvent,
)


PUBLISHED_AT = datetime(2026, 7, 14, 0, 30, tzinfo=UTC)
FETCHED_AT = datetime(2026, 7, 14, 0, 31, tzinfo=UTC)
CONTENT_HASH = "a" * 64


def article() -> NewsArticle:
    return NewsArticle(
        article_id="eastmoney-20260714-1",
        canonical_url="https://finance.eastmoney.com/a/202607141.html",
        publisher="东方财富",
        title="政策支持先进制造业发展",
        published_at=PUBLISHED_AT,
        fetched_at=FETCHED_AT,
        content_hash=CONTENT_HASH,
        raw_snapshot=b"published source snapshot",
        source_verified=True,
    )


def citation() -> EvidenceCitation:
    return EvidenceCitation(
        citation_id="citation-1",
        article_id="eastmoney-20260714-1",
        canonical_url="https://finance.eastmoney.com/a/202607141.html",
        publisher="东方财富",
        published_at=PUBLISHED_AT,
        quoted_text="政策支持先进制造业发展",
        content_hash=CONTENT_HASH,
    )


def test_article_preserves_immutable_raw_evidence() -> None:
    item = article()

    assert item.raw_snapshot == b"published source snapshot"
    assert item.canonical_url == "https://finance.eastmoney.com/a/202607141.html"
    with pytest.raises(ValidationError):
        item.publisher = "其他来源"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("published_at", datetime(2026, 7, 14, 0, 30)),
        ("fetched_at", datetime(2026, 7, 14, 0, 31)),
        ("fetched_at", PUBLISHED_AT - timedelta(seconds=1)),
        ("content_hash", "not-a-sha256"),
        ("raw_snapshot", b""),
    ],
)
def test_article_rejects_invalid_evidence_boundaries(field: str, value: object) -> None:
    values = article().model_dump()
    values[field] = value

    with pytest.raises(ValidationError):
        NewsArticle(**values)


def test_normalized_event_keeps_asset_links_and_evidence() -> None:
    event = NormalizedNewsEvent(
        event_id="event-1",
        event_type="industrial_policy",
        headline="先进制造政策事件",
        occurred_at=PUBLISHED_AT,
        normalized_at=FETCHED_AT,
        affected_instruments=((AssetKind.A_SHARE, "600000"),),
        industries=("高端制造",),
        themes=("政策支持",),
        citations=(citation(),),
        association_confidence="0.82",
        review_state="pending",
    )

    assert event.citations[0].article_id == article().article_id
    assert event.affected_instruments == ((AssetKind.A_SHARE, "600000"),)


def test_ai_interpretation_requires_fact_citations_and_explicit_interpretation_labels() -> None:
    with pytest.raises(ValidationError):
        InterpretationStatement(
            statement_id="statement-1",
            kind="fact",
            text="政策已经发布。",
            citation_ids=(),
        )

    interpretation = AIInterpretation(
        interpretation_id="interpretation-1",
        event_id="event-1",
        generated_at=FETCHED_AT,
        provider="local",
        model="deterministic-fallback",
        prompt_version="news-v1",
        statements=(
            InterpretationStatement(
                statement_id="statement-1",
                kind="fact",
                text="政策支持先进制造业发展。",
                citation_ids=("citation-1",),
            ),
            InterpretationStatement(
                statement_id="statement-2",
                kind="interpretation",
                text="这可能改善行业情绪，但不等同于买入信号。",
            ),
        ),
        citations=(citation(),),
    )

    assert interpretation.statements[1].kind == "interpretation"


def test_ai_interpretation_rejects_missing_or_future_citations() -> None:
    statement = InterpretationStatement(
        statement_id="statement-1",
        kind="fact",
        text="政策已经发布。",
        citation_ids=("citation-1",),
    )

    with pytest.raises(ValidationError):
        AIInterpretation(
            interpretation_id="interpretation-1",
            event_id="event-1",
            generated_at=FETCHED_AT,
            provider="cloud",
            model="model-1",
            prompt_version="news-v1",
            statements=(statement.model_copy(update={"citation_ids": ("missing",)}),),
            citations=(citation(),),
        )

    future_citation = citation().model_copy(
        update={"published_at": FETCHED_AT + timedelta(seconds=1)}
    )
    with pytest.raises(ValidationError):
        AIInterpretation(
            interpretation_id="interpretation-2",
            event_id="event-1",
            generated_at=FETCHED_AT,
            provider="cloud",
            model="model-1",
            prompt_version="news-v1",
            statements=(statement,),
            citations=(future_citation,),
        )
