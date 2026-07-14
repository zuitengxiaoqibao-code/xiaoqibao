from collections.abc import Mapping
from decimal import Decimal
import re

from qibao_api.contracts.instruments import (
    validate_a_share_code,
    validate_convertible_bond_code,
)
from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.news import (
    EvidenceCitation,
    NewsArticle,
    NormalizedNewsEvent,
)


class DeterministicNewsLinker:
    def __init__(
        self,
        *,
        instrument_aliases: Mapping[tuple[AssetKind, str], tuple[str, ...]],
        industry_keywords: Mapping[str, tuple[str, ...]],
        theme_keywords: Mapping[str, tuple[str, ...]],
    ) -> None:
        self.instrument_aliases = instrument_aliases
        self.industry_keywords = industry_keywords
        self.theme_keywords = theme_keywords

    def link(self, article: NewsArticle) -> NormalizedNewsEvent:
        text = f"{article.title}\n{article.summary or ''}"
        configured = tuple(
            instrument
            for instrument, aliases in self.instrument_aliases.items()
            if any(alias in text for alias in aliases) or instrument[1] in text
        )
        explicit = tuple(
            instrument
            for code in dict.fromkeys(re.findall(r"(?<!\d)\d{6}(?!\d)", text))
            if (instrument := _recognized_instrument(code)) is not None
        )
        instruments = tuple(dict.fromkeys((*configured, *explicit)))
        industries = tuple(
            name
            for name, keywords in self.industry_keywords.items()
            if any(keyword in text for keyword in keywords)
        )
        themes = tuple(
            name
            for name, keywords in self.theme_keywords.items()
            if any(keyword in text for keyword in keywords)
        )
        has_taxonomy = bool(industries or themes)
        confidence = (
            Decimal("1")
            if instruments
            else Decimal("0.60")
            if has_taxonomy
            else Decimal("0")
        )
        review_state = (
            "verified"
            if article.source_verified and confidence >= Decimal("0.80")
            else "pending"
        )
        citation = EvidenceCitation(
            citation_id=f"citation-{article.article_id}",
            article_id=article.article_id,
            canonical_url=article.canonical_url,
            publisher=article.publisher,
            published_at=article.published_at,
            quoted_text=article.title,
            content_hash=article.content_hash,
        )
        return NormalizedNewsEvent(
            event_id=f"event-{article.article_id}",
            event_type="market_news",
            headline=article.title,
            occurred_at=article.published_at,
            normalized_at=article.fetched_at,
            affected_instruments=instruments,
            industries=industries,
            themes=themes,
            citations=(citation,),
            association_confidence=confidence,
            review_state=review_state,
        )


def _recognized_instrument(code: str) -> tuple[AssetKind, str] | None:
    try:
        return AssetKind.A_SHARE, validate_a_share_code(code)
    except ValueError:
        pass
    try:
        return AssetKind.CONVERTIBLE_BOND, validate_convertible_bond_code(code)
    except ValueError:
        return None
