from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from qibao_api.contracts.market import AssetKind


class RiskRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(min_length=1, max_length=128)
    rule_version: str = Field(min_length=1, max_length=64)
    asset: AssetKind
    description: str = Field(min_length=1)
    parameters: tuple[tuple[str, str], ...] = ()
    created_at: datetime


class RiskDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(min_length=1, max_length=128)
    order_id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(pattern=r"^\d{6}$")
    asset: AssetKind
    outcome: Literal["approve", "reduce", "reject", "observe_only"]
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=128)
    evidence: tuple[str, ...] = Field(min_length=1)
    rule_id: str = Field(min_length=1, max_length=128)
    rule_version: str = Field(min_length=1, max_length=64)
    decided_at: datetime


class ComplianceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: str = Field(min_length=1, max_length=128)
    asset: AssetKind
    source: str = Field(min_length=1, max_length=128)
    permission_state: Literal["authorized", "pending", "revoked"]
    permission_reference: str = Field(min_length=1)
    disclaimer_version: str = Field(min_length=1, max_length=64)
    user_acknowledged_at: datetime | None = None
    recorded_at: datetime


class AuditFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding_id: str = Field(min_length=1, max_length=128)
    asset: AssetKind
    finding_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=128)
    severity: Literal["low", "medium", "high", "critical"]
    evidence: tuple[str, ...] = Field(min_length=1)
    input_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    owner_department: Literal["xingbu", "dongchang", "libu"]
    resolution_state: Literal["open", "investigating", "resolved", "accepted"]
    detected_at: datetime
