import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from qibao_api.contracts.market import AssetKind
from qibao_api.dongchang.audit import AuditEngine, AuditThresholds
from qibao_api.dongchang.models import (
    AuditInput,
    NewsEvidence,
    RejectionMetrics,
    SignalFrequency,
    Snapshot,
    SourceObservation,
)
from qibao_api.dongchang.repository import AuditFindingRepository


NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


def _input(**changes: object) -> AuditInput:
    values: dict[str, object] = {
        "audit_run_id": "run-1",
        "asset": AssetKind.A_SHARE,
        "recommendation": Snapshot(
            snapshot_id="recommendation-1",
            conclusion="observe",
            evidence_link="snapshot://recommendation-1",
            captured_at=NOW,
        ),
        "outcome": Snapshot(
            snapshot_id="outcome-1",
            conclusion="up-3-percent",
            evidence_link="snapshot://outcome-1",
            captured_at=NOW,
        ),
    }
    values.update(changes)
    return AuditInput(**values)


def test_clean_input_produces_no_findings() -> None:
    audit_input = _input(
        news_evidence=(
            NewsEvidence(
                evidence_id="news-1",
                content_fingerprint="sha256:a",
                source="eastmoney",
                evidence_link="news://1",
            ),
        ),
        source_observations=(
            SourceObservation(
                field="close",
                value="10.00",
                source="tdx",
                evidence_link="quote://tdx/1",
            ),
            SourceObservation(
                field="close",
                value="10.00",
                source="tencent",
                evidence_link="quote://tencent/1",
            ),
        ),
        signal_frequency=SignalFrequency(baseline_count=10, current_count=14),
        rejection_metrics=RejectionMetrics(
            baseline_rejected=2, baseline_total=10, current_rejected=4, current_total=10
        ),
    )

    assert AuditEngine().audit(audit_input) == ()


def test_all_detectors_hit_at_inclusive_threshold_boundaries() -> None:
    audit_input = _input(
        news_evidence=(
            NewsEvidence(
                evidence_id="news-1",
                content_fingerprint="sha256:same",
                source="eastmoney",
                evidence_link="news://1",
            ),
            NewsEvidence(
                evidence_id="news-2",
                content_fingerprint="sha256:same",
                source="ths",
                evidence_link="news://2",
            ),
        ),
        source_observations=(
            SourceObservation(
                field="close",
                value="10.00",
                source="tdx",
                evidence_link="quote://tdx/1",
            ),
            SourceObservation(
                field="close",
                value="10.01",
                source="tencent",
                evidence_link="quote://tencent/1",
            ),
        ),
        signal_frequency=SignalFrequency(baseline_count=10, current_count=15),
        rejection_metrics=RejectionMetrics(
            baseline_rejected=3, baseline_total=10, current_rejected=5, current_total=10
        ),
    )

    findings = AuditEngine(
        AuditThresholds(
            signal_relative_drift=Decimal("0.50"),
            rejection_rate=Decimal("0.50"),
            rejection_rate_increase=Decimal("0.20"),
        ),
        clock=lambda: NOW,
    ).audit(audit_input)

    assert [finding.finding_type for finding in findings] == [
        "duplicate_news_evidence",
        "source_field_conflict",
        "signal_frequency_drift",
        "abnormal_rejection_rate",
    ]
    assert [finding.severity for finding in findings] == ["medium", "high", "high", "critical"]
    assert all(
        finding.input_snapshot_ids == ("recommendation-1", "outcome-1")
        for finding in findings
    )
    assert findings[0].evidence == ("news://1", "news://2")
    assert [finding.owner_department for finding in findings] == [
        "dongchang",
        "dongchang",
        "xingbu",
        "xingbu",
    ]


def test_zero_signal_baseline_only_drifts_when_current_has_signals() -> None:
    engine = AuditEngine(clock=lambda: NOW)

    assert engine.audit(
        _input(signal_frequency=SignalFrequency(baseline_count=0, current_count=0))
    ) == ()
    assert engine.audit(
        _input(signal_frequency=SignalFrequency(baseline_count=0, current_count=1))
    )[0].finding_type == "signal_frequency_drift"


def test_rejection_rate_requires_both_absolute_and_increase_thresholds() -> None:
    engine = AuditEngine(clock=lambda: NOW)

    below_absolute = _input(
        rejection_metrics=RejectionMetrics(
            baseline_rejected=1, baseline_total=10, current_rejected=4, current_total=10
        )
    )
    below_increase = _input(
        rejection_metrics=RejectionMetrics(
            baseline_rejected=4, baseline_total=10, current_rejected=5, current_total=10
        )
    )

    assert engine.audit(below_absolute) == ()
    assert engine.audit(below_increase) == ()


def test_asset_isolation_rejects_cross_asset_evidence() -> None:
    with pytest.raises(ValidationError, match="asset"):
        _input(
            news_evidence=(
                NewsEvidence(
                    evidence_id="news-1",
                    asset=AssetKind.CONVERTIBLE_BOND,
                    content_fingerprint="sha256:a",
                    source="eastmoney",
                    evidence_link="news://1",
                ),
            )
        )


def test_audit_does_not_mutate_original_input() -> None:
    audit_input = _input(
        signal_frequency=SignalFrequency(baseline_count=1, current_count=2)
    )
    before = audit_input.model_dump(mode="json")

    AuditEngine(clock=lambda: NOW).audit(audit_input)

    assert audit_input.model_dump(mode="json") == before
    with pytest.raises(ValidationError):
        audit_input.recommendation.conclusion = "blocked"


def test_repository_recovers_findings_after_restart_and_forbids_mutation(tmp_path) -> None:
    database = tmp_path / "audit.sqlite3"
    finding = AuditEngine(clock=lambda: NOW).audit(
        _input(signal_frequency=SignalFrequency(baseline_count=1, current_count=2))
    )[0]
    repository = AuditFindingRepository(database)
    repository.append(finding)
    repository.close()

    reopened = AuditFindingRepository(database)
    assert reopened.list_findings(asset=AssetKind.A_SHARE) == [finding]
    assert reopened.list_findings(asset=AssetKind.CONVERTIBLE_BOND) == []
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        reopened.connection.execute(
            "UPDATE audit_findings SET severity = 'low' WHERE finding_id = ?",
            (finding.finding_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        reopened.connection.execute(
            "DELETE FROM audit_findings WHERE finding_id = ?", (finding.finding_id,)
        )
    reopened.close()


def test_repository_rejects_duplicate_finding_id(tmp_path) -> None:
    repository = AuditFindingRepository(tmp_path / "audit.sqlite3")
    finding = AuditEngine(clock=lambda: NOW).audit(
        _input(signal_frequency=SignalFrequency(baseline_count=1, current_count=2))
    )[0]
    repository.append(finding)

    with pytest.raises(ValueError, match="already exists"):
        repository.append(finding)
    repository.close()
