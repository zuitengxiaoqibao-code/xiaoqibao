from datetime import UTC, date, datetime

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import AuditFinding
from qibao_api.shangshu.postclose_context import RepositoryPostcloseContextSource


NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


class Paper:
    def list_order_outcomes_between(self, start, end):
        assert start == datetime(2026, 7, 14, 1, 25, tzinfo=UTC)
        assert end == datetime(2026, 7, 14, 7, 0, tzinfo=UTC)
        return [
            {"order_id": "filled-1", "status": "filled", "rejection_reason": None},
            {"order_id": "rejected-1", "status": "rejected", "rejection_reason": "stale_quote"},
            {"order_id": "pending-1", "status": "pending", "rejection_reason": None},
        ]


class Audit:
    def list_findings(self, *, asset):
        assert asset == AssetKind.A_SHARE
        return [AuditFinding(
            finding_id="finding-1", asset=AssetKind.A_SHARE,
            finding_type="abnormal_rejection_rate", severity="high",
            evidence=("snapshot://1",), input_snapshot_ids=("snapshot-1",),
            owner_department="dongchang", resolution_state="open",
            detected_at=datetime(2026, 7, 14, 7, 0, tzinfo=UTC),
        )]


def test_postclose_context_collects_terminal_orders_and_audit_findings() -> None:
    context = RepositoryPostcloseContextSource(Paper(), Audit()).snapshot(
        date(2026, 7, 14), NOW
    )

    assert context.signal_outcome_ids == ("filled-1", "rejected-1")
    assert context.error_codes == ("stale_quote",)
    assert context.risk_event_ids == ("finding-1",)
