from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from qibao_api.a_shares.models import CandidateBoard, CandidateEntry, FactorSnapshot
from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.news import EvidenceCitation, NormalizedNewsEvent
from qibao_api.shangshu.decision_runtime import RepositoryCandidateFactorSource
from qibao_api.shangshu.decision_repository import DecisionRepository
from qibao_api.zhongshu.decision_ai import DecisionAIResult
from qibao_api.zhongshu.premarket_decision import (
    CandidateInputSnapshot, ComplianceInputSnapshot, MarketRiskInputSnapshot,
    PremarketDecisionService,
)


TZ = timezone(timedelta(hours=8))
TRADE_DATE = date(2026, 7, 15)
PREVIOUS = date(2026, 7, 14)
NOW = datetime(2026, 7, 15, 9, 20, tzinfo=TZ)
WINDOW_END = datetime(2026, 7, 15, 9, 25, tzinfo=TZ)
LATE_TIME = datetime(2026, 7, 15, 10, 0, tzinfo=TZ)


def entry(symbol: str, horizon: str) -> CandidateEntry:
    factor = FactorSnapshot(
        symbol=symbol, as_of=TRADE_DATE, close="10", return_5d="0.02",
        return_20d="0.03", distance_ma20="0.01", volume_ratio_5_20="1.2",
        volatility_20d="0.1", drawdown_60d="-0.05", liquidity_amount_20d="1000000",
        source="frozen-history",
    )
    return CandidateEntry(
        symbol=symbol, horizon=horizon, score="20", score_breakdown={"trend": Decimal("20")},
        factor_snapshot=factor,
    )


def candidate_input(*, captured_at=NOW, history_available=True, changed=False):
    board = CandidateBoard(
        snapshot_id="candidates-2" if changed else "candidates-1", as_of=TRADE_DATE,
        short_term=[entry("600000", "short_term")], swing=[entry("000001", "swing")],
    )
    return CandidateInputSnapshot(
        board=board, captured_at=captured_at, history_available=history_available,
    )


def test_premarket_uses_requested_cutoff_for_candidate_capture() -> None:
    frozen = candidate_input()
    source = RepositoryCandidateFactorSource(
        CandidateService(frozen.board), clock=lambda: LATE_TIME,
    )

    snapshot = source.candidates(TRADE_DATE, cutoff=WINDOW_END)

    assert snapshot.captured_at == WINDOW_END


def news(
    *, headline="已核验公告", event_id="news-1", symbol="600000",
    asset=AssetKind.A_SHARE, event_type="announcement", themes=(),
    occurred_at=NOW - timedelta(minutes=20), normalized_at=NOW - timedelta(minutes=10),
):
    citation = EvidenceCitation(
        citation_id="citation-1", article_id="article-1", canonical_url="https://example.com/1",
        publisher="交易所", published_at=occurred_at, quoted_text="已核验公告",
        content_hash="a" * 64,
    )
    return NormalizedNewsEvent(
        event_id=event_id, event_type=event_type, headline=headline,
        occurred_at=occurred_at, normalized_at=normalized_at,
        affected_instruments=((asset, symbol),), themes=themes, citations=(citation,),
        association_confidence="1", review_state="verified",
    )


class Calendar:
    def __init__(self, confirmed=True): self.confirmed = confirmed
    def is_trading_day(self, value): return self.confirmed and value == TRADE_DATE
    def previous_trading_day(self, value): return PREVIOUS


class CandidateService:
    def __init__(self, value): self.value = value
    def candidates(self, as_of, cutoff=None): return self.value


class NewsRepository:
    def __init__(self, events=(), interpretations=()):
        self._events, self._interpretations = events, interpretations
    def events(self): return list(self._events)
    def interpretations(self): return list(self._interpretations)


class Compliance:
    def __init__(self, captured_at=NOW, available=True):
        self.value = ComplianceInputSnapshot(
            snapshot_id="compliance-1", captured_at=captured_at, available=available,
            allowed=True, version="rules-v1", risks=("禁止真实下单",),
        )
    def check(self, trading_date, now): return self.value


class MarketRisk:
    def __init__(self, captured_at=NOW):
        self.value = MarketRiskInputSnapshot(
            snapshot_id="risk-1", captured_at=captured_at, available=True,
            market_state="range", version="risk-v1", summary="市场震荡",
            risks=("市场波动可能放大",),
        )
    def summarize(self, trading_date, now): return self.value


class AI:
    def __init__(self, ready=True, generated_at=NOW): self.ready, self.generated_at = ready, generated_at
    def explain(self, request):
        return DecisionAIResult(
            status="ready" if self.ready else "unavailable",
            explanation="通俗解释" if self.ready else None, statements=(), provider="p", model="m",
            prompt_version="v", generated_at=self.generated_at,
            evidence_ids=tuple(item.evidence_id for item in request.evidence),
            invalid_output_count=0, provider_error_count=0 if self.ready else 1,
        )


def service(tmp_path, *, candidates=None, events=(), ai=None, compliance=None, risk=None, calendar=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    return PremarketDecisionService(
        candidate_service=CandidateService(candidates if candidates is not None else candidate_input()),
        news_repository=NewsRepository(events), compliance_checker=compliance or Compliance(),
        market_risk_summary=risk or MarketRisk(), ai_gateway=ai or AI(),
        decision_repository=repository, trading_calendar=calendar or Calendar(), clock=lambda: NOW,
    ), repository


def test_window_and_confirmation_fail_explicitly(tmp_path) -> None:
    subject, _ = service(tmp_path, calendar=Calendar(False))
    with pytest.raises(ValueError, match="unconfirmed"):
        subject.run(TRADE_DATE, NOW)
    subject, _ = service(tmp_path / "other")
    with pytest.raises(ValueError, match="window"):
        subject.run(TRADE_DATE, datetime(2026, 7, 14, 15, 0, tzinfo=TZ))


def test_short_term_and_swing_remain_separate_and_future_news_is_excluded(tmp_path) -> None:
    future = news(occurred_at=NOW + timedelta(minutes=1), normalized_at=NOW + timedelta(minutes=2))
    subject, _ = service(tmp_path, events=(news(), future))
    result = subject.run(TRADE_DATE, NOW)
    assert [(item.symbol, item.horizon) for item in result.advice] == [
        ("600000", "intraday"), ("000001", "swing")
    ]
    assert result.snapshot.news_event_ids == ("news-1",)
    assert result.advice[0].action == "observe"
    assert result.advice[1].action == "observe"
    assert result.plans == ()


@pytest.mark.parametrize("headline", ["并非利好", "利好出尽"])
def test_headline_words_never_upgrade_or_downgrade_ranked_candidate(tmp_path, headline) -> None:
    subject, _ = service(tmp_path, events=(news(headline=headline),))
    result = subject.run(TRADE_DATE, NOW)
    advice = next(item for item in result.advice if item.symbol == "600000")
    assert advice.action == "observe"
    assert all(evidence.source == "frozen-history" for evidence in advice.supporting_evidence)
    assert advice.contrary_evidence == ()


def test_adverse_risk_event_is_contrary_and_downgrades_observation(tmp_path) -> None:
    adverse = news(event_type="company_risk", themes=("风险事件",))
    subject, _ = service(tmp_path, events=(adverse,))
    result = subject.run(TRADE_DATE, NOW)
    advice = next(item for item in result.advice if item.symbol == "600000")
    assert advice.action == "wait"
    assert [item.evidence_id for item in advice.contrary_evidence] == ["news-news-1"]
    assert all(item.evidence_id != "news-news-1" for item in advice.supporting_evidence)


def test_mixed_news_never_places_adverse_or_unknown_event_in_supporting_evidence(tmp_path) -> None:
    unknown = news(event_id="unknown", headline="方向未明")
    adverse = news(event_id="adverse", event_type="risk_notice")
    subject, _ = service(tmp_path, events=(unknown, adverse))
    result = subject.run(TRADE_DATE, NOW)
    advice = next(item for item in result.advice if item.symbol == "600000")
    assert [item.evidence_id for item in advice.supporting_evidence] == [
        "factor-candidates-1-short_term-600000"
    ]
    assert [item.evidence_id for item in advice.contrary_evidence] == ["news-adverse"]


def test_unrelated_and_bond_news_do_not_change_hash_or_append_cycle(tmp_path) -> None:
    subject, repository = service(tmp_path)
    first = subject.run(TRADE_DATE, NOW)
    subject.news_repository._events = (
        news(event_id="unrelated", symbol="600519"),
        news(event_id="bond", symbol="110000", asset=AssetKind.CONVERTIBLE_BOND),
    )
    second = subject.run(TRADE_DATE, NOW)
    assert second == first
    assert second.snapshot.news_event_ids == ()
    assert len(repository.cycles()) == 1


@pytest.mark.parametrize("port", ["candidate", "compliance", "risk"])
def test_future_required_inputs_are_rejected_without_advice(tmp_path, port) -> None:
    future = NOW + timedelta(minutes=1)
    kwargs = {}
    if port == "candidate":
        kwargs["candidates"] = candidate_input(captured_at=future)
    elif port == "compliance":
        kwargs["compliance"] = Compliance(future)
    else:
        kwargs["risk"] = MarketRisk(future)
    subject, _ = service(tmp_path, **kwargs)
    result = subject.run(TRADE_DATE, NOW)
    assert result.snapshot.status == "blocked"
    assert result.advice == ()


def test_missing_history_degrades_without_invented_advice(tmp_path) -> None:
    subject, _ = service(tmp_path, candidates=candidate_input(history_available=False))
    result = subject.run(TRADE_DATE, NOW)
    assert result.snapshot.status == "blocked"
    assert result.advice == ()


def test_ai_unavailable_retains_deterministic_advice_without_explanation(tmp_path) -> None:
    subject, repository = service(tmp_path, events=(news(),), ai=AI(False))
    result = subject.run(TRADE_DATE, NOW)
    assert result.snapshot.status == "partial"
    assert result.snapshot.ai_status == "unavailable"
    assert len(result.advice) == 2
    assert all(item.plain_language_explanation is None for item in result.advice)
    stored = repository.latest(TRADE_DATE, "premarket")
    assert stored.advice[0].quantitative_result["ai_model"] == "m"
    assert stored.advice[0].quantitative_result["ai_provider_error_count"] == Decimal("1")


def test_future_ai_interpretation_is_excluded(tmp_path) -> None:
    subject, _ = service(tmp_path, events=(news(),), ai=AI(True, NOW + timedelta(minutes=1)))
    result = subject.run(TRADE_DATE, NOW)
    assert result.snapshot.ai_status == "unavailable"
    assert all(item.plain_language_explanation is None for item in result.advice)


def test_identical_input_is_idempotent_and_changed_input_appends(tmp_path) -> None:
    subject, repository = service(tmp_path, events=(news(),))
    first = subject.run(TRADE_DATE, NOW)
    assert subject.run(TRADE_DATE, NOW) == first
    subject.candidate_service.value = candidate_input(changed=True)
    second = subject.run(TRADE_DATE, NOW)
    assert second.snapshot.sequence == 2
    assert second.snapshot.previous_snapshot_id == first.snapshot.snapshot_id
    assert len(repository.cycles()) == 2
