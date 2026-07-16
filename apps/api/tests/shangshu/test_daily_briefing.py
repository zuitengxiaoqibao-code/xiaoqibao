from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from qibao_api.contracts.briefing import DailyBriefing, PostcloseContext
from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.news import EvidenceCitation, NormalizedNewsEvent
from qibao_api.shangshu.daily_briefing import DailyBriefingWorkflow
from qibao_api.shangshu.briefing_repository import BriefingRepository


TRADE_DATE = date(2026, 7, 14)


def event(event_id: str, when: datetime, *, verified: bool = True) -> NormalizedNewsEvent:
    return NormalizedNewsEvent(
        event_id=event_id, event_type="industrial_policy", headline=event_id,
        occurred_at=when, normalized_at=when,
        affected_instruments=((AssetKind.A_SHARE, "600000"),),
        industries=("高端制造",), themes=("政策支持",),
        citations=(EvidenceCitation(
            citation_id=f"citation-{event_id}", article_id=f"article-{event_id}",
            canonical_url=f"https://news.example/{event_id}", publisher="测试来源",
            published_at=when, quoted_text=event_id, content_hash="a" * 64,
        ),), association_confidence=Decimal("1"),
        review_state="verified" if verified else "pending",
    )


class Calendar:
    def is_trading_day(self, value: date) -> bool:
        return value == TRADE_DATE

    def previous_trading_day(self, value: date) -> date:
        assert value == TRADE_DATE
        return date(2026, 7, 13)


class News:
    def __init__(self, events):
        self.items = list(events)
        self.effective_items = None
        self.fail_once = False

    def events(self):
        return self._read(self.items)

    def effective_events(self, *, cutoff=None):
        return self._read(
            self.items if self.effective_items is None else self.effective_items
        )

    def _read(self, items):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("temporary read failure")
        return list(items)

    def interpretations(self):
        return []


def test_premarket_freezes_overnight_inputs_and_excludes_unverified_watchlist(tmp_path) -> None:
    news = News([
        event("overnight", datetime(2026, 7, 13, 23, 0, tzinfo=UTC)),
        event("unverified", datetime(2026, 7, 14, 0, 0, tzinfo=UTC), verified=False),
        event("future", datetime(2026, 7, 14, 2, 0, tzinfo=UTC)),
    ])
    reports = BriefingRepository(tmp_path / "briefing.sqlite3")
    workflow = DailyBriefingWorkflow(news, reports, Calendar())

    report = workflow.run("premarket", TRADE_DATE,
                          now=datetime(2026, 7, 14, 1, 20, tzinfo=UTC))

    assert report.event_ids == ("overnight", "unverified")
    assert report.sections.watchlist == ((AssetKind.A_SHARE, "600000"),)
    frozen = reports.reports()[0]
    news.items.append(event("later", datetime(2026, 7, 14, 1, 21, tzinfo=UTC)))
    assert reports.reports()[0] == frozen
    reports.close()


def test_intraday_suppresses_events_already_emitted_by_prior_run(tmp_path) -> None:
    news = News([event("first", datetime(2026, 7, 14, 2, 0, tzinfo=UTC))])
    reports = BriefingRepository(tmp_path / "briefing.sqlite3")
    workflow = DailyBriefingWorkflow(news, reports, Calendar())

    first = workflow.run("intraday", TRADE_DATE,
                         now=datetime(2026, 7, 14, 2, 5, tzinfo=UTC))
    news.items.append(event("second", datetime(2026, 7, 14, 2, 10, tzinfo=UTC)))
    second = workflow.run("intraday", TRADE_DATE,
                          now=datetime(2026, 7, 14, 2, 15, tzinfo=UTC))

    assert first.event_ids == ("first",)
    assert second.event_ids == ("second",)
    reports.close()


def test_briefing_uses_effective_event_risk_taxonomy(tmp_path) -> None:
    raw = event("corrected", datetime(2026, 7, 14, 2, 0, tzinfo=UTC)).model_copy(
        update={"event_type": "market_news", "themes": ("风险事件",)}
    )
    news = News([raw])
    news.effective_items = [raw.model_copy(update={"themes": ()})]
    reports = BriefingRepository(tmp_path / "briefing.sqlite3")

    report = DailyBriefingWorkflow(news, reports, Calendar()).run(
        "intraday", TRADE_DATE, now=datetime(2026, 7, 14, 2, 5, tzinfo=UTC)
    )

    assert report.event_ids == ("corrected",)
    assert report.sections.risk_event_ids == ()
    reports.close()


def test_failed_run_is_recorded_and_can_be_retried(tmp_path) -> None:
    news = News([event("overnight", datetime(2026, 7, 13, 23, 0, tzinfo=UTC))])
    news.fail_once = True
    reports = BriefingRepository(tmp_path / "briefing.sqlite3")
    workflow = DailyBriefingWorkflow(news, reports, Calendar())

    with pytest.raises(RuntimeError, match="temporary"):
        workflow.run("premarket", TRADE_DATE,
                     now=datetime(2026, 7, 14, 1, 20, tzinfo=UTC))
    completed: DailyBriefing = workflow.run(
        "premarket", TRADE_DATE, now=datetime(2026, 7, 14, 1, 20, tzinfo=UTC)
    )

    runs = reports.runs()
    assert [run["status"] for run in runs] == ["failed", "completed"]
    assert runs[1]["attempt"] == 2
    assert runs[1]["report_id"] == completed.report_id
    reports.close()


def test_non_trading_day_fails_closed_without_report(tmp_path) -> None:
    reports = BriefingRepository(tmp_path / "briefing.sqlite3")
    workflow = DailyBriefingWorkflow(News([]), reports, Calendar())

    with pytest.raises(ValueError, match="trading day"):
        workflow.run("premarket", date(2026, 7, 15),
                     now=datetime(2026, 7, 15, 1, 20, tzinfo=UTC))
    assert reports.reports() == []
    reports.close()


def test_postclose_freezes_signal_outcomes_errors_and_risk_events(tmp_path) -> None:
    class Context:
        def snapshot(self, trading_date, now):
            assert trading_date == TRADE_DATE
            return PostcloseContext(
                signal_outcome_ids=("order-1",),
                error_codes=("stale_quote",),
                risk_event_ids=("finding-1",),
            )

    reports = BriefingRepository(tmp_path / "briefing.sqlite3")
    workflow = DailyBriefingWorkflow(News([]), reports, Calendar(), Context())

    report = workflow.run(
        "postclose", TRADE_DATE, now=datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
    )

    assert report.sections.signal_outcome_ids == ("order-1",)
    assert report.sections.error_codes == ("stale_quote",)
    assert report.sections.risk_event_ids == ("finding-1",)
    reports.close()
