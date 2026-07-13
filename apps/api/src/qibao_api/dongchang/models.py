from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from qibao_api.contracts.market import AssetKind


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Snapshot(FrozenModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    conclusion: str = Field(min_length=1)
    evidence_link: str = Field(min_length=1)
    captured_at: AwareDatetime


class NewsEvidence(FrozenModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    asset: AssetKind = AssetKind.A_SHARE
    content_fingerprint: str = Field(min_length=1, max_length=256)
    source: str = Field(min_length=1, max_length=128)
    evidence_link: str = Field(min_length=1)


class SourceObservation(FrozenModel):
    asset: AssetKind = AssetKind.A_SHARE
    field: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=128)
    evidence_link: str = Field(min_length=1)


class SignalFrequency(FrozenModel):
    baseline_count: int = Field(ge=0)
    current_count: int = Field(ge=0)


class RejectionMetrics(FrozenModel):
    baseline_rejected: int = Field(ge=0)
    baseline_total: int = Field(gt=0)
    current_rejected: int = Field(ge=0)
    current_total: int = Field(gt=0)

    @model_validator(mode="after")
    def rejected_cannot_exceed_total(self) -> "RejectionMetrics":
        if self.baseline_rejected > self.baseline_total:
            raise ValueError("baseline_rejected cannot exceed baseline_total")
        if self.current_rejected > self.current_total:
            raise ValueError("current_rejected cannot exceed current_total")
        return self


class AuditInput(FrozenModel):
    audit_run_id: str = Field(min_length=1, max_length=128)
    asset: AssetKind
    recommendation: Snapshot
    outcome: Snapshot
    news_evidence: tuple[NewsEvidence, ...] = ()
    source_observations: tuple[SourceObservation, ...] = ()
    signal_frequency: SignalFrequency | None = None
    rejection_metrics: RejectionMetrics | None = None

    @model_validator(mode="after")
    def evidence_must_match_audit_asset(self) -> "AuditInput":
        evidence_assets = [item.asset for item in self.news_evidence]
        evidence_assets.extend(item.asset for item in self.source_observations)
        if any(asset != self.asset for asset in evidence_assets):
            raise ValueError("evidence asset must match audit asset")
        return self
