from datetime import UTC, date, datetime
from types import SimpleNamespace

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import AuditFinding
from qibao_api.shangshu.postclose_context import RepositoryPostcloseContextSource


NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


class Decisions:
    def cycles(self, trading_date, phase):
        assert trading_date == date(2026, 7, 14)
        if phase != "intraday":
            return []
        return [SimpleNamespace(
            snapshot=SimpleNamespace(generated_at=datetime(2026, 7, 14, 6, 0, tzinfo=UTC)),
            advice=(SimpleNamespace(
                advice_id="advice-1",
                created_at=datetime(2026, 7, 14, 5, 0, tzinfo=UTC),
            ),),
        )]


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


def test_postclose_context_collects_decisions_and_audit_findings() -> None:
    context = RepositoryPostcloseContextSource(Decisions(), Audit()).snapshot(
        date(2026, 7, 14), NOW
    )

    assert context.signal_outcome_ids == ("advice-1",)
    assert context.error_codes == ()
    assert context.risk_event_ids == ("finding-1",)
