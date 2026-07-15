from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from qibao_api.a_shares.models import CandidateBoard, CandidateEntry, FactorSnapshot
from qibao_api.gongbu.market_feed import MarketFeedSnapshot
from qibao_api.shangshu.decision_runtime import (
    DecisionSymbolSource,
    DeterministicIntradayEvaluator,
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

    def candidates(self, _date):
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
    result = RepositoryRiskSource(Audit(), Candidates(board([12, 8]))).summarize(
        date(2026, 7, 15), NOW
    )

    assert result.available is True
    assert result.market_state == "strong"
    assert result.risks == ()


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


def candidate_input() -> CandidateInputSnapshot:
    factor = FactorSnapshot(
        symbol="600000", as_of=date(2026, 7, 15), close="9.16",
        return_5d="0.03", return_20d="-0.03", distance_ma20="0.02",
        volume_ratio_5_20="0.96", volatility_20d="0.01", drawdown_60d="-0.08",
        liquidity_amount_20d="600000000", source="baidu",
    )
    entry = CandidateEntry(
        symbol="600000", horizon="short_term", score="40",
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
