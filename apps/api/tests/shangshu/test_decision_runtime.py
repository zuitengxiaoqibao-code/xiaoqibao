from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from qibao_api.a_shares.models import (
    CandidateBoard,
    CandidateEntry,
    CandidateExclusion,
    FactorSnapshot,
)
from qibao_api.gongbu.market_feed import MarketFeedSnapshot
from qibao_api.shangshu.decision_runtime import (
    DecisionSymbolSource,
    DeterministicIntradayEvaluator,
    RepositoryCandidateFactorSource,
    RepositoryEvidenceSource,
    RepositoryRiskSource,
)
from qibao_api.shangshu.intraday_monitor import IntradayEvaluationContext
from qibao_api.zhongshu.premarket_decision import (
    CandidateInputSnapshot,
    ComplianceInputSnapshot,
    MarketRiskInputSnapshot,
)


NOW = datetime(2026, 7, 15, 9, 20, tzinfo=timezone.utc)


class Candidates:
    def __init__(self, board):
        self.board = board
        self.cutoffs = []

    def candidates(self, _date, *, cutoff=None):
        self.cutoffs.append(cutoff)
        return self.board


class Audit:
    def __init__(self, findings=()):
        self.findings = findings

    def list_findings(self, *, asset):
        return list(self.findings)


def board(scores):
    entries = [SimpleNamespace(score=score) for score in scores]
    return SimpleNamespace(
        universe_status="ready" if entries else "empty", short_term=entries,
        swing=[], snapshot_id="candidate-1", model_dump=lambda mode: {"scores": scores},
    )


def test_market_risk_is_available_from_candidate_breadth_without_audit_findings():
    candidates = Candidates(board([12, 8]))
    result = RepositoryRiskSource(Audit(), candidates).summarize(
        date(2026, 7, 15), NOW
    )

    assert result.available is True
    assert result.market_state == "strong"
    assert result.risks == ()
    assert candidates.cutoffs == [NOW]


def test_audit_findings_are_an_additional_market_risk_signal():
    finding = SimpleNamespace(
        detected_at=NOW, resolution_state="open", severity="critical",
        finding_type="data_drift", model_dump=lambda mode: {"finding_id": "f1"},
    )
    result = RepositoryRiskSource(Audit((finding,)), Candidates(board([12]))).summarize(
        date(2026, 7, 15), NOW
    )

    assert result.available is True
    assert result.market_state == "weak"
    assert result.risks == ("data_drift",)


def test_market_risk_degrades_when_candidate_factor_data_is_unavailable():
    result = RepositoryRiskSource(Audit(), Candidates(board([]))).summarize(
        date(2026, 7, 15), NOW
    )

    assert result.available is False
    assert result.market_state == "insufficient_data"
    assert "market_factor_evidence_unavailable" in result.risks


def test_market_risk_includes_verified_topics_industries_and_candidate_fund_flow():
    candidate_board = SimpleNamespace(
        universe_status="ready",
        short_term=[SimpleNamespace(symbol="600000", score=12)],
        swing=[SimpleNamespace(symbol="600519", score=8)],
        snapshot_id="candidate-1",
        model_dump=lambda mode: {"symbols": ["600000", "600519"]},
    )
    candidates = Candidates(candidate_board)
    news = SimpleNamespace(effective_events=lambda cutoff=None: [
        SimpleNamespace(
            review_state="verified", themes=("人工智能",), industries=("软件服务",),
            occurred_at=NOW, normalized_at=NOW,
        ),
        SimpleNamespace(
            review_state="verified", themes=("旧热点",), industries=("旧行业",),
            occurred_at=NOW - timedelta(days=2), normalized_at=NOW - timedelta(days=2),
        ),
    ])
    classifications = SimpleNamespace(latest=lambda symbol, as_of, cutoff=None: SimpleNamespace(
        industry="银行" if symbol == "600000" else "白酒",
    ))
    flows = SimpleNamespace(latest=lambda symbol, as_of, cutoff=None: SimpleNamespace(
        flow_direction="inflow" if symbol == "600000" else "outflow",
    ))

    result = RepositoryRiskSource(
        Audit(), candidates, news_repository=news,
        classification_repository=classifications, fund_flow_repository=flows,
    ).summarize(date(2026, 7, 15), NOW)

    assert result.hot_topics == ("人工智能",)
    assert result.industries == ("软件服务", "银行", "白酒")
    assert (result.fund_flow_inflow_count, result.fund_flow_outflow_count) == (1, 1)
    assert result.fund_flow_available_count == 2


def test_market_risk_deduplicates_fund_flow_for_short_and_swing_membership():
    candidate_board = SimpleNamespace(
        universe_status="ready",
        short_term=[SimpleNamespace(symbol="600000", score=12)],
        swing=[SimpleNamespace(symbol="600000", score=8)],
        snapshot_id="candidate-1",
        model_dump=lambda mode: {"symbols": ["600000"]},
    )
    flows = SimpleNamespace(latest=lambda symbol, as_of, cutoff=None: SimpleNamespace(
        flow_direction="outflow",
    ))

    result = RepositoryRiskSource(
        Audit(), Candidates(candidate_board), fund_flow_repository=flows,
    ).summarize(date(2026, 7, 15), NOW)

    assert result.fund_flow_available_count == 1
    assert result.fund_flow_outflow_count == 1


def candidate_input(symbol: str = "600000") -> CandidateInputSnapshot:
    factor = FactorSnapshot(
        symbol=symbol, as_of=date(2026, 7, 15), close="9.16",
        return_5d="0.03", return_20d="-0.03", distance_ma20="0.02",
        volume_ratio_5_20="0.96", volatility_20d="0.01", drawdown_60d="-0.08",
        liquidity_amount_20d="600000000", source="baidu",
    )
    entry = CandidateEntry(
        symbol=symbol, horizon="short_term", score="40",
        score_breakdown={"trend": Decimal("10")}, factor_snapshot=factor,
    )
    return CandidateInputSnapshot(
        board=CandidateBoard(
            snapshot_id="candidate-live", as_of=date(2026, 7, 15),
            short_term=[entry], swing=[],
        ),
        captured_at=datetime(2026, 7, 15, 13, 0, tzinfo=timezone(timedelta(hours=8))),
        history_available=True,
    )


def test_symbol_source_uses_current_candidates_when_decision_pool_is_empty():
    repository = SimpleNamespace(cycles=lambda *_args: [])
    source = SimpleNamespace(candidates=lambda _date: candidate_input())

    symbols = DecisionSymbolSource(repository, source)(
        datetime(2026, 7, 15, 13, 0, tzinfo=timezone(timedelta(hours=8)))
    )

    assert symbols == ("600000",)


def test_symbol_source_merges_existing_cycles_with_current_candidates():
    advice = SimpleNamespace(symbol="600000")
    cycle = SimpleNamespace(advice=(advice,))
    repository = SimpleNamespace(cycles=lambda *_args: [cycle])
    source = SimpleNamespace(candidates=lambda _date: candidate_input("600519"))

    symbols = DecisionSymbolSource(repository, source)(
        datetime(2026, 7, 15, 13, 0, tzinfo=timezone(timedelta(hours=8)))
    )

    assert symbols == ("600000", "600519")


def test_candidate_factor_source_marks_a_computed_empty_board_as_available():
    empty = CandidateBoard(
        snapshot_id="candidate-empty", as_of=date(2026, 7, 15),
        short_term=[], swing=[],
        exclusions=[CandidateExclusion(
            symbol="600000", reason_code="insufficient_liquidity",
        )],
    )

    result = RepositoryCandidateFactorSource(Candidates(empty)).candidates(
        date(2026, 7, 15)
    )

    assert result.board.universe_status == "empty"
    assert result.history_available is True


def test_repository_evidence_source_uses_effective_events():
    raw = SimpleNamespace(
        event_id="raw",
        review_state="verified",
        occurred_at=NOW,
        normalized_at=NOW,
    )
    effective = SimpleNamespace(
        event_id="effective",
        review_state="verified",
        occurred_at=NOW,
        normalized_at=NOW,
    )
    repository = SimpleNamespace(
        events=lambda: [raw], effective_events=lambda cutoff=None: [effective]
    )

    result = RepositoryEvidenceSource(repository).snapshot(now=NOW, cutoff=NOW)

    assert [item.event_id for item in result] == ["effective"]


def test_intraday_evaluator_seeds_observation_when_premarket_advice_is_empty():
    local_now = datetime(2026, 7, 15, 13, 0, tzinfo=timezone(timedelta(hours=8)))
    candidates = candidate_input()
    quote = MarketFeedSnapshot(
        symbol="600000", price="9.20", change="0.04", change_percent="0.44",
        volume="1000", source="tencent", observed_at=local_now,
        fetched_at=local_now.astimezone(timezone.utc), quality="ready",
        source_snapshot_id="quote-live",
    )
    risk = MarketRiskInputSnapshot(
        snapshot_id="risk-live", captured_at=local_now, available=True,
        market_state="range", version="risk-v1", summary="range", risks=(),
    )
    compliance = ComplianceInputSnapshot(
        snapshot_id="compliance-live", captured_at=local_now, available=True,
        allowed=True, version="compliance-v1", risks=(),
    )

    result = DeterministicIntradayEvaluator().evaluate(IntradayEvaluationContext(
        now=local_now, window_start=local_now.replace(hour=9, minute=25),
        window_end=local_now, quotes=(quote,), current_advice=(),
        candidate_factor_input=candidates, risk_input=risk,
        compliance_input=compliance, evidence_input=(),
    ))

    assert [item.symbol for item in result.advice] == ["600000"]
    assert result.advice[0].action == "observe"
    assert "premarket_snapshot_unavailable" in result.advice[0].risks


@pytest.mark.parametrize(
    ("change_percent", "action", "conclusion"),
    [
        ("3.20", "observe", "盘中走强，等待放量确认"),
        ("-3.20", "wait", "盘中走弱，等待止跌确认"),
    ],
)
def test_intraday_evaluator_turns_live_quote_change_into_a_beginner_friendly_signal(
    change_percent, action, conclusion,
):
    local_now = datetime(2026, 7, 15, 13, 0, tzinfo=timezone(timedelta(hours=8)))
    candidates = candidate_input()
    quote = MarketFeedSnapshot(
        symbol="600000", price="9.20", change="0.04", change_percent=change_percent,
        volume="1000", source="tencent", observed_at=local_now,
        fetched_at=local_now.astimezone(timezone.utc), quality="ready",
        source_snapshot_id="quote-live",
    )
    risk = MarketRiskInputSnapshot(
        snapshot_id="risk-live", captured_at=local_now, available=True,
        market_state="range", version="risk-v1", summary="range", risks=(),
    )
    compliance = ComplianceInputSnapshot(
        snapshot_id="compliance-live", captured_at=local_now, available=True,
        allowed=True, version="compliance-v1", risks=(),
    )

    result = DeterministicIntradayEvaluator().evaluate(IntradayEvaluationContext(
        now=local_now, window_start=local_now.replace(hour=9, minute=25),
        window_end=local_now, quotes=(quote,), current_advice=(),
        candidate_factor_input=candidates, risk_input=risk,
        compliance_input=compliance, evidence_input=(),
    ))

    assert result.advice[0].action == action
    assert result.advice[0].conclusion == conclusion
    assert result.market_state in {"strong", "weak"}
    assert any("盘中行情" in item.summary for item in result.advice[0].supporting_evidence)


def test_intraday_evaluator_attaches_verified_news_as_supporting_or_contrary_evidence():
    local_now = datetime(2026, 7, 15, 13, 0, tzinfo=timezone(timedelta(hours=8)))
    quote = MarketFeedSnapshot(
        symbol="600000", price="9.20", change="0.04", change_percent="0.44",
        volume="1000", source="tencent", observed_at=local_now,
        fetched_at=local_now.astimezone(timezone.utc), quality="ready",
        source_snapshot_id="quote-live",
    )
    risk = MarketRiskInputSnapshot(
        snapshot_id="risk-live", captured_at=local_now, available=True,
        market_state="range", version="risk-v1", summary="range", risks=(),
    )
    compliance = ComplianceInputSnapshot(
        snapshot_id="compliance-live", captured_at=local_now, available=True,
        allowed=True, version="compliance-v1", risks=(),
    )
    event = SimpleNamespace(
        event_id="news-risk", affected_instruments=(("a_share", "600000"),),
        event_type="risk_notice", themes=("风险事件",), normalized_at=local_now,
        citations=(SimpleNamespace(publisher="交易所", canonical_url="https://example.com"),),
        headline="公司风险提示",
    )

    result = DeterministicIntradayEvaluator().evaluate(IntradayEvaluationContext(
        now=local_now, window_start=local_now.replace(hour=9, minute=25),
        window_end=local_now, quotes=(quote,), current_advice=(),
        candidate_factor_input=candidate_input(), risk_input=risk,
        compliance_input=compliance, evidence_input=(event,),
    ))

    advice = result.advice[0]
    assert [item.evidence_id for item in advice.contrary_evidence] == ["news-news-risk"]
    assert "风险新闻" in advice.risks


@pytest.mark.parametrize("failure", ["stale_quote", "compliance_denied"])
def test_intraday_evaluator_blocks_new_advice_when_live_gate_is_not_valid(failure):
    local_now = datetime(2026, 7, 15, 13, 0, tzinfo=timezone(timedelta(hours=8)))
    observed_at = local_now - timedelta(minutes=4) if failure == "stale_quote" else local_now
    quote = MarketFeedSnapshot(
        symbol="600000", price="9.20", change="0.04", change_percent="0.44",
        volume="1000", source="tencent", observed_at=observed_at,
        fetched_at=local_now.astimezone(timezone.utc), quality="ready",
        source_snapshot_id="quote-live",
    )
    risk = MarketRiskInputSnapshot(
        snapshot_id="risk-live", captured_at=local_now, available=True,
        market_state="range", version="risk-v1", summary="range", risks=(),
    )
    compliance = ComplianceInputSnapshot(
        snapshot_id="compliance-live", captured_at=local_now, available=True,
        allowed=failure != "compliance_denied", version="compliance-v1", risks=(),
    )

    result = DeterministicIntradayEvaluator().evaluate(IntradayEvaluationContext(
        now=local_now, window_start=local_now.replace(hour=9, minute=25),
        window_end=local_now, quotes=(quote,), current_advice=(),
        candidate_factor_input=candidate_input(), risk_input=risk,
        compliance_input=compliance, evidence_input=(),
    ))

    assert result.advice == ()
    assert result.status == "blocked"
    assert result.data_quality == "blocked"


def test_intraday_evaluator_replaces_stale_advice_with_a_new_candidate():
    local_now = datetime(2026, 7, 15, 13, 0, tzinfo=timezone(timedelta(hours=8)))
    candidates = candidate_input("600519")
    quotes = tuple(
        MarketFeedSnapshot(
            symbol=symbol, price=price, change="0.04", change_percent="0.44",
            volume="1000", source="tencent", observed_at=local_now,
            fetched_at=local_now.astimezone(timezone.utc), quality="ready",
            source_snapshot_id=f"quote-{symbol}",
        )
        for symbol, price in (("600000", "9.20"), ("600519", "1400"))
    )
    risk = MarketRiskInputSnapshot(
        snapshot_id="risk-live", captured_at=local_now, available=True,
        market_state="range", version="risk-v1", summary="range", risks=(),
    )
    compliance = ComplianceInputSnapshot(
        snapshot_id="compliance-live", captured_at=local_now, available=True,
        allowed=True, version="compliance-v1", risks=(),
    )
    existing = DeterministicIntradayEvaluator()._seed_advice(
        SimpleNamespace(
            candidate_factor_input=candidate_input(), now=local_now,
            risk_input=risk, compliance_input=compliance,
        ),
        {"600000": quotes[0]},
    )

    result = DeterministicIntradayEvaluator().evaluate(IntradayEvaluationContext(
        now=local_now, window_start=local_now.replace(hour=9, minute=25),
        window_end=local_now, quotes=quotes, current_advice=existing,
        candidate_factor_input=candidates, risk_input=risk,
        compliance_input=compliance, evidence_input=(),
    ))

    assert {item.symbol for item in result.advice} == {"600519"}


def test_intraday_evaluator_preserves_existing_advice_when_candidates_are_unavailable():
    local_now = datetime(2026, 7, 15, 13, 0, tzinfo=timezone(timedelta(hours=8)))
    available = candidate_input()
    unavailable = CandidateInputSnapshot(
        board=CandidateBoard(
            snapshot_id="candidate-unavailable", as_of=date(2026, 7, 15),
            universe_status="empty", short_term=[], swing=[],
        ),
        captured_at=local_now,
        history_available=False,
    )
    quote = MarketFeedSnapshot(
        symbol="600000", price="9.20", change="0.04", change_percent="0.44",
        volume="1000", source="tencent", observed_at=local_now,
        fetched_at=local_now.astimezone(timezone.utc), quality="ready",
        source_snapshot_id="quote-600000",
    )
    risk = MarketRiskInputSnapshot(
        snapshot_id="risk-live", captured_at=local_now, available=False,
        market_state="insufficient_data", version="risk-v1", summary="unavailable",
        risks=("market_factor_evidence_unavailable",),
    )
    compliance = ComplianceInputSnapshot(
        snapshot_id="compliance-live", captured_at=local_now, available=True,
        allowed=True, version="compliance-v1", risks=(),
    )
    existing = DeterministicIntradayEvaluator()._seed_advice(
        SimpleNamespace(
            candidate_factor_input=available, now=local_now,
            risk_input=risk, compliance_input=compliance,
        ),
        {"600000": quote},
    )

    result = DeterministicIntradayEvaluator().evaluate(IntradayEvaluationContext(
        now=local_now, window_start=local_now.replace(hour=9, minute=25),
        window_end=local_now, quotes=(quote,), current_advice=existing,
        candidate_factor_input=unavailable, risk_input=risk,
        compliance_input=compliance, evidence_input=(),
    ))

    assert {(item.symbol, item.horizon) for item in result.advice} == {
        ("600000", "intraday")
    }
    assert result.status == "blocked"


def test_intraday_evaluator_removes_existing_advice_after_a_computed_empty_board():
    local_now = datetime(2026, 7, 15, 13, 0, tzinfo=timezone(timedelta(hours=8)))
    available = candidate_input()
    computed_empty = RepositoryCandidateFactorSource(Candidates(CandidateBoard(
        snapshot_id="candidate-empty", as_of=date(2026, 7, 15),
        short_term=[], swing=[],
        exclusions=[CandidateExclusion(
            symbol="600000", reason_code="insufficient_liquidity",
        )],
    )), clock=lambda: local_now).candidates(date(2026, 7, 15))
    quote = MarketFeedSnapshot(
        symbol="600000", price="9.20", change="0.04", change_percent="0.44",
        volume="1000", source="tencent", observed_at=local_now,
        fetched_at=local_now.astimezone(timezone.utc), quality="ready",
        source_snapshot_id="quote-600000",
    )
    risk = MarketRiskInputSnapshot(
        snapshot_id="risk-live", captured_at=local_now, available=True,
        market_state="range", version="risk-v1", summary="range", risks=(),
    )
    compliance = ComplianceInputSnapshot(
        snapshot_id="compliance-live", captured_at=local_now, available=True,
        allowed=True, version="compliance-v1", risks=(),
    )
    existing = DeterministicIntradayEvaluator()._seed_advice(
        SimpleNamespace(
            candidate_factor_input=available, now=local_now,
            risk_input=risk, compliance_input=compliance,
        ),
        {"600000": quote},
    )

    result = DeterministicIntradayEvaluator().evaluate(IntradayEvaluationContext(
        now=local_now, window_start=local_now.replace(hour=9, minute=25),
        window_end=local_now, quotes=(quote,), current_advice=existing,
        candidate_factor_input=computed_empty, risk_input=risk,
        compliance_input=compliance, evidence_input=(),
    ))

    assert computed_empty.history_available is True
    assert result.advice == ()
