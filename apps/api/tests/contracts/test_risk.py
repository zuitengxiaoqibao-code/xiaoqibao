from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import AuditFinding, ComplianceRecord, RiskRule


NOW = datetime(2026, 7, 13, 9, 30, tzinfo=UTC)


def test_risk_rule_is_versioned_asset_specific_and_frozen() -> None:
    rule = RiskRule(
        rule_id="market_quality", rule_version="2026-07-13.1",
        asset=AssetKind.A_SHARE, description="Require verified market evidence",
        created_at=NOW,
    )
    with pytest.raises(ValidationError):
        rule.rule_version = "changed"


def test_compliance_record_preserves_source_authorization_history() -> None:
    record = ComplianceRecord(
        record_id="compliance-1", asset=AssetKind.A_SHARE, source="tencent",
        permission_state="authorized", permission_reference="license://tencent/2026",
        disclaimer_version="2026-07-01", user_acknowledged_at=NOW, recorded_at=NOW,
    )
    assert record.asset is AssetKind.A_SHARE
    with pytest.raises(ValidationError):
        record.permission_state = "revoked"


def test_audit_finding_links_immutable_evidence_and_input_snapshots() -> None:
    finding = AuditFinding(
        finding_id="finding-1", asset=AssetKind.A_SHARE,
        finding_type="duplicate_news_evidence", severity="high",
        evidence=("evidence://news/1",), input_snapshot_ids=("snapshot-1",),
        owner_department="dongchang", resolution_state="open", detected_at=NOW,
    )
    assert finding.input_snapshot_ids == ("snapshot-1",)
    with pytest.raises(ValidationError):
        AuditFinding.model_validate({**finding.model_dump(), "evidence": (" ",)})
