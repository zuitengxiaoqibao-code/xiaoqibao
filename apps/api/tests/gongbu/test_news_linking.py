import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.news import NewsArticle
from qibao_api.gongbu.news_linking import DeterministicNewsLinker


NOW = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)


def article(title: str, summary: str, *, verified: bool = True) -> NewsArticle:
    raw = f"{title}|{summary}".encode()
    return NewsArticle(
        article_id=hashlib.sha256(raw).hexdigest()[:12],
        canonical_url="https://news.example/item",
        publisher="测试来源",
        title=title,
        summary=summary,
        published_at=NOW,
        fetched_at=NOW,
        content_hash=hashlib.sha256(raw).hexdigest(),
        raw_snapshot=raw,
        source_verified=verified,
    )


def linker() -> DeterministicNewsLinker:
    return DeterministicNewsLinker(
        instrument_aliases={
            (AssetKind.A_SHARE, "600519"): ("贵州茅台", "茅台"),
            (AssetKind.CONVERTIBLE_BOND, "113065"): ("齐鲁转债",),
        },
        industry_keywords={"高端制造": ("先进制造", "工业母机")},
        theme_keywords={"政策支持": ("支持政策", "专项政策")},
    )


def test_linker_maps_explicit_aliases_and_taxonomy_with_verified_state() -> None:
    event = linker().link(
        article("贵州茅台发布经营公告", "先进制造支持政策同步发布。")
    )

    assert event.affected_instruments == ((AssetKind.A_SHARE, "600519"),)
    assert event.industries == ("高端制造",)
    assert event.themes == ("政策支持",)
    assert event.association_confidence == 1
    assert event.review_state == "verified"
    assert event.citations[0].article_id == event.event_id.removeprefix("event-")


def test_linker_keeps_keyword_only_and_unverified_sources_pending() -> None:
    keyword_only = linker().link(article("产业动态", "先进制造支持政策落地。"))
    unverified = linker().link(
        article("齐鲁转债出现异动", "市场消息。", verified=False)
    )

    assert keyword_only.affected_instruments == ()
    assert keyword_only.association_confidence == Decimal("0.60")
    assert keyword_only.review_state == "pending"
    assert unverified.affected_instruments == (
        (AssetKind.CONVERTIBLE_BOND, "113065"),
    )
    assert unverified.review_state == "pending"


def test_linker_does_not_guess_unconfigured_entities() -> None:
    event = linker().link(article("某公司签署协议", "或与白酒行业有关。"))

    assert event.affected_instruments == ()
    assert event.industries == ()
    assert event.themes == ()
    assert event.association_confidence == 0
    assert event.review_state == "pending"


def test_linker_recognizes_explicit_supported_security_codes() -> None:
    event = linker().link(article("600000发布重要公告", "公司公告原文。"))

    assert event.affected_instruments == ((AssetKind.A_SHARE, "600000"),)
    assert event.review_state == "verified"
