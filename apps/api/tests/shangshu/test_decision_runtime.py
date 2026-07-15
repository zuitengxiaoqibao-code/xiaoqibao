from datetime import date, datetime, timezone
from types import SimpleNamespace

from qibao_api.shangshu.decision_runtime import RepositoryRiskSource


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
