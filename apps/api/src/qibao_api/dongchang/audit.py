from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field

from qibao_api.contracts.risk import AuditFinding
from qibao_api.dongchang.models import AuditInput


class AuditThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_relative_drift: Decimal = Field(default=Decimal("0.50"), ge=0)
    rejection_rate: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)
    rejection_rate_increase: Decimal = Field(default=Decimal("0.20"), ge=0, le=1)


class AuditEngine:
    def __init__(
        self,
        thresholds: AuditThresholds | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.thresholds = thresholds or AuditThresholds()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def audit(self, audit_input: AuditInput) -> tuple[AuditFinding, ...]:
        findings: list[AuditFinding] = []
        findings.extend(self._duplicate_news(audit_input))
        findings.extend(self._source_conflicts(audit_input))
        frequency = audit_input.signal_frequency
        if frequency is not None:
            if frequency.baseline_count == 0:
                drifted = frequency.current_count > 0
            else:
                relative_change = Decimal(abs(frequency.current_count - frequency.baseline_count)) / Decimal(
                    frequency.baseline_count
                )
                drifted = relative_change >= self.thresholds.signal_relative_drift
            if drifted:
                findings.append(
                    self._finding(
                        audit_input,
                        "signal_frequency_drift",
                        "high",
                        (audit_input.recommendation.evidence_link, audit_input.outcome.evidence_link),
                        "xingbu",
                        "signal-frequency",
                    )
                )
        metrics = audit_input.rejection_metrics
        if metrics is not None:
            baseline_rate = Decimal(metrics.baseline_rejected) / Decimal(metrics.baseline_total)
            current_rate = Decimal(metrics.current_rejected) / Decimal(metrics.current_total)
            if (
                current_rate >= self.thresholds.rejection_rate
                and current_rate - baseline_rate >= self.thresholds.rejection_rate_increase
            ):
                findings.append(
                    self._finding(
                        audit_input,
                        "abnormal_rejection_rate",
                        "critical",
                        (audit_input.recommendation.evidence_link, audit_input.outcome.evidence_link),
                        "xingbu",
                        "rejection-rate",
                    )
                )
        return tuple(findings)

    def _duplicate_news(self, audit_input: AuditInput) -> list[AuditFinding]:
        groups: dict[str, list] = defaultdict(list)
        for item in audit_input.news_evidence:
            groups[item.content_fingerprint].append(item)
        return [
            self._finding(
                audit_input,
                "duplicate_news_evidence",
                "medium",
                tuple(item.evidence_link for item in sorted(items, key=lambda item: item.evidence_id)),
                "dongchang",
                fingerprint,
            )
            for fingerprint, items in sorted(groups.items())
            if len(items) > 1
        ]

    def _source_conflicts(self, audit_input: AuditInput) -> list[AuditFinding]:
        groups: dict[str, list] = defaultdict(list)
        for item in audit_input.source_observations:
            groups[item.field].append(item)
        findings = []
        for field, items in sorted(groups.items()):
            if len({item.value for item in items}) <= 1:
                continue
            links = tuple(
                item.evidence_link for item in sorted(items, key=lambda item: (item.source, item.value))
            )
            findings.append(
                self._finding(
                    audit_input, "source_field_conflict", "high", links, "dongchang", field
                )
            )
        return findings

    def _finding(
        self,
        audit_input: AuditInput,
        finding_type: str,
        severity: str,
        evidence: tuple[str, ...],
        owner: str,
        discriminator: str,
    ) -> AuditFinding:
        identity = "|".join((audit_input.audit_run_id, audit_input.asset.value, finding_type, discriminator))
        finding_id = f"audit-{sha256(identity.encode('utf-8')).hexdigest()[:24]}"
        return AuditFinding(
            finding_id=finding_id,
            asset=audit_input.asset,
            finding_type=finding_type,
            severity=severity,
            evidence=evidence,
            input_snapshot_ids=(
                audit_input.recommendation.snapshot_id,
                audit_input.outcome.snapshot_id,
            ),
            owner_department=owner,
            resolution_state="open",
            detected_at=self._clock(),
        )
