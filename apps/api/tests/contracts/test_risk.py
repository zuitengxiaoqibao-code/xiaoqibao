from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import (
    AuditFinding,
    ComplianceRecord,
    RiskDecision,
    RiskRule,
)


NOW = datetime(2026, 7, 13, 9, 30, tzinfo=UTC)


def test_risk_rule_is_versioned_asset_specific_and_frozen() -> None:
    rule = RiskRule(
        rule_id="max_position",
        rule_version="2026-07-13.1",
        asset=AssetKind.A_SHARE,
        description="Limit a single position",
        created_at=NOW,
    )

    with pytest.raises(ValidationError):
        rule.rule_version = "2026-07-14.1"


@pytest.mark.parametrize("outcome", ["approve", "reduce", "reject", "observe_only"])
def test_risk_decision_accepts_only_supported_outcomes(outcome: str) -> None:
    decision = RiskDecision(
        decision_id="decision-1",
        order_id="order-1",
        symbol="600000",
        asset=AssetKind.A_SHARE,
        outcome=outcome,
        reason_code="within_position_limit",
        evidence=("snapshot://orders/order-1",),
        rule_id="max_position",
        rule_version="2026-07-13.1",
        decided_at=NOW,
    )

    assert decision.outcome == outcome

    with pytest.raises(ValidationError):
        decision.outcome = "reject"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("outcome", "observe-only"),
        ("reason_code", "Not machine readable"),
        ("evidence", ()),
        ("rule_version", ""),
        ("decided_at", None),
    ],
)
def test_risk_decision_rejects_invalid_or_missing_audit_context(
    field: str, value: object
) -> None:
    values = {
        "decision_id": "decision-1",
        "order_id": "order-1",
        "symbol": "600000",
        "asset": AssetKind.A_SHARE,
        "outcome": "approve",
        "reason_code": "within_position_limit",
        "evidence": ("snapshot://orders/order-1",),
        "rule_id": "max_position",
        "rule_version": "2026-07-13.1",
        "decided_at": NOW,
    }
    values[field] = value

    with pytest.raises(ValidationError):
        RiskDecision(**values)


def test_compliance_record_preserves_source_authorization_history() -> None:
    record = ComplianceRecord(
        record_id="compliance-1",
        asset=AssetKind.CONVERTIBLE_BOND,
        source="tencent",
        permission_state="authorized",
        permission_reference="license://tencent/2026",
        disclaimer_version="2026-07-01",
        user_acknowledged_at=NOW,
        recorded_at=NOW,
    )

    assert record.asset is AssetKind.CONVERTIBLE_BOND
    with pytest.raises(ValidationError):
        record.permission_state = "revoked"


def test_audit_finding_links_immutable_evidence_and_input_snapshots() -> None:
    finding = AuditFinding(
        finding_id="finding-1",
        asset=AssetKind.A_SHARE,
        finding_type="duplicate_news_evidence",
        severity="high",
        evidence=("evidence://news/1", "evidence://news/2"),
        input_snapshot_ids=("snapshot-1",),
        owner_department="dongchang",
        resolution_state="open",
        detected_at=NOW,
    )

    assert finding.input_snapshot_ids == ("snapshot-1",)
    with pytest.raises(ValidationError):
        finding.resolution_state = "resolved"
