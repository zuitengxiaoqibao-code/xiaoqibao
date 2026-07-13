import sqlite3
from datetime import datetime, timedelta, timezone
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
LATER = NOW + timedelta(days=1)


def _input(**changes: object) -> AuditInput:
    values: dict[str, object] = {
        "audit_run_id": "run-1",
        "asset": AssetKind.A_SHARE,
        "recommendation": Snapshot(
            snapshot_id="recommendation-1",
            asset=AssetKind.A_SHARE,
            symbol="600000",
            conclusion="bullish",
            evidence_link="snapshot://recommendation-1",
            captured_at=NOW,
        ),
        "outcome": Snapshot(
            snapshot_id="outcome-1",
            asset=AssetKind.A_SHARE,
            symbol="600000",
            conclusion="bullish",
            evidence_link="snapshot://outcome-1",
            captured_at=LATER,
        ),
    }
    values.update(changes)
    return AuditInput(**values)


def test_clean_input_produces_no_findings() -> None:
    audit_input = _input(
        news_evidence=(
            NewsEvidence(
                evidence_id="news-1",
                symbol="600000",
                content_fingerprint="sha256:a",
                source="eastmoney",
                evidence_link="news://1",
            ),
        ),
        source_observations=(
            SourceObservation(
                symbol="600000",
                as_of=NOW,
                field="close",
                value="10.00",
                source="tdx",
                evidence_link="quote://tdx/1",
            ),
            SourceObservation(
                symbol="600000",
                as_of=NOW,
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


def test_recommendation_comparison_distinguishes_match_from_opposite_without_mutation() -> None:
    matching = _input()
    opposite = _input(
        outcome=Snapshot(
            snapshot_id="outcome-opposite",
            asset=AssetKind.A_SHARE,
            symbol="600000",
            conclusion="bearish",
            evidence_link="snapshot://outcome-opposite",
            captured_at=LATER,
        )
    )
    before = opposite.model_dump(mode="json")

    assert AuditEngine(clock=lambda: LATER).audit(matching) == ()
    findings = AuditEngine(clock=lambda: LATER).audit(opposite)

    assert [finding.finding_type for finding in findings] == [
        "recommendation_outcome_deviation"
    ]
    assert findings[0].severity == "high"
    assert opposite.model_dump(mode="json") == before


@pytest.mark.parametrize(
    ("recommendation_changes", "outcome_changes", "message"),
    [
        ({}, {"captured_at": NOW}, "strictly later"),
        ({}, {"snapshot_id": "recommendation-1"}, "snapshot_id"),
        ({}, {"symbol": "000001"}, "symbol"),
        ({}, {"asset": AssetKind.CONVERTIBLE_BOND}, "asset"),
    ],
)
def test_snapshot_pair_must_be_distinct_ordered_and_same_security(
    recommendation_changes: dict[str, object],
    outcome_changes: dict[str, object],
    message: str,
) -> None:
    recommendation_values = _input().recommendation.model_dump()
    outcome_values = _input().outcome.model_dump()
    recommendation_values.update(recommendation_changes)
    outcome_values.update(outcome_changes)

    with pytest.raises(ValidationError, match=message):
        _input(
            recommendation=Snapshot(**recommendation_values),
            outcome=Snapshot(**outcome_values),
        )


def test_source_conflicts_are_scoped_to_same_security_and_timestamp() -> None:
    observations = (
        SourceObservation(
            asset=AssetKind.A_SHARE,
            symbol="600000",
            as_of=NOW,
            field="close",
            value="10.00",
            source="tdx",
            evidence_link="quote://tdx/600000",
        ),
        SourceObservation(
            asset=AssetKind.A_SHARE,
            symbol="000001",
            as_of=NOW,
            field="close",
            value="11.00",
            source="tencent",
            evidence_link="quote://tencent/000001",
        ),
    )

    assert AuditEngine().audit(_input(source_observations=observations)) == ()


def test_all_detectors_hit_at_inclusive_threshold_boundaries() -> None:
    audit_input = _input(
        news_evidence=(
            NewsEvidence(
                evidence_id="news-1",
                symbol="600000",
                content_fingerprint="sha256:same",
                source="eastmoney",
                evidence_link="news://1",
            ),
            NewsEvidence(
                evidence_id="news-2",
                symbol="600000",
                content_fingerprint="sha256:same",
                source="ths",
                evidence_link="news://2",
            ),
        ),
        source_observations=(
            SourceObservation(
                symbol="600000",
                as_of=NOW,
                field="close",
                value="10.00",
                source="tdx",
                evidence_link="quote://tdx/1",
            ),
            SourceObservation(
                symbol="600000",
                as_of=NOW,
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
                    symbol="110059",
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
        audit_input.recommendation.conclusion = "bearish"


def test_repository_recovers_findings_after_restart_and_forbids_mutation(tmp_path) -> None:
    database = tmp_path / "audit.sqlite3"
    audit_input = _input(signal_frequency=SignalFrequency(baseline_count=1, current_count=2))
    finding = AuditEngine(clock=lambda: NOW).audit(audit_input)[0]
    repository = AuditFindingRepository(database)
    repository.append_audit(audit_input, (finding,))
    repository.close()

    reopened = AuditFindingRepository(database)
    assert reopened.list_findings(asset=AssetKind.A_SHARE) == [finding]
    assert reopened.list_findings(asset=AssetKind.CONVERTIBLE_BOND) == []
    restored = reopened.get_snapshot("recommendation-1")
    assert restored.snapshot == audit_input.recommendation
    assert restored.content_hash == audit_input.recommendation.canonical_content_hash()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        reopened.connection.execute(
            "UPDATE audit_findings SET severity = 'low' WHERE finding_id = ?",
            (finding.finding_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        reopened.connection.execute(
            "DELETE FROM audit_findings WHERE finding_id = ?", (finding.finding_id,)
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        reopened.connection.execute(
            "UPDATE audit_snapshots SET conclusion = 'bearish' WHERE snapshot_id = ?",
            ("recommendation-1",),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        reopened.connection.execute(
            "DELETE FROM audit_snapshots WHERE snapshot_id = ?", ("recommendation-1",)
        )
    reopened.close()


def test_repository_rejects_duplicate_finding_id(tmp_path) -> None:
    repository = AuditFindingRepository(tmp_path / "audit.sqlite3")
    finding = AuditEngine(clock=lambda: NOW).audit(
        _input(signal_frequency=SignalFrequency(baseline_count=1, current_count=2))
    )[0]
    audit_input = _input(signal_frequency=SignalFrequency(baseline_count=1, current_count=2))
    repository.append_audit(audit_input, (finding,))

    with pytest.raises(ValueError, match="already exists"):
        repository.append_audit(audit_input, (finding,))
    repository.close()


def test_database_rejects_finding_snapshot_links_to_unknown_snapshots(tmp_path) -> None:
    repository = AuditFindingRepository(tmp_path / "audit.sqlite3")

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        repository.connection.execute(
            """INSERT INTO audit_finding_snapshots (finding_id, snapshot_id, position)
               VALUES ('missing-finding', 'missing-snapshot', 0)"""
        )
    repository.close()
