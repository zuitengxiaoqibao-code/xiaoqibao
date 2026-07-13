import hashlib
import json
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from qibao_api.contracts.market import AssetKind


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Snapshot(FrozenModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    asset: AssetKind
    symbol: str = Field(pattern=r"^\d{6}$")
    conclusion: Literal["bullish", "neutral", "bearish"]
    evidence_link: str = Field(min_length=1)
    captured_at: AwareDatetime

    def canonical_content_hash(self) -> str:
        content = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


class NewsEvidence(FrozenModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    asset: AssetKind = AssetKind.A_SHARE
    symbol: str = Field(pattern=r"^\d{6}$")
    content_fingerprint: str = Field(min_length=1, max_length=256)
    source: str = Field(min_length=1, max_length=128)
    evidence_link: str = Field(min_length=1)


class SourceObservation(FrozenModel):
    asset: AssetKind = AssetKind.A_SHARE
    symbol: str = Field(pattern=r"^\d{6}$")
    as_of: AwareDatetime
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
    def validate_snapshot_and_evidence_scope(self) -> "AuditInput":
        if self.recommendation.snapshot_id == self.outcome.snapshot_id:
            raise ValueError("recommendation and outcome snapshot_id must differ")
        if self.outcome.captured_at <= self.recommendation.captured_at:
            raise ValueError("outcome captured_at must be strictly later than recommendation")
        if self.recommendation.asset != self.outcome.asset or self.asset != self.recommendation.asset:
            raise ValueError("snapshot asset must match audit asset")
        if self.recommendation.symbol != self.outcome.symbol:
            raise ValueError("snapshot symbol must match")
        if any(item.asset != self.asset for item in self.news_evidence):
            raise ValueError("news evidence asset must match audit asset")
        if any(item.symbol != self.recommendation.symbol for item in self.news_evidence):
            raise ValueError("news evidence symbol must match snapshot symbol")
        if any(item.asset != self.asset for item in self.source_observations):
            raise ValueError("source observation asset must match audit asset")
        return self
