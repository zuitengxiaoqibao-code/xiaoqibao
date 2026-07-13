from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import ComplianceRecord
from qibao_api.dependencies import get_compliance_repository
from qibao_api.libu_compliance.repository import ComplianceRepository


router = APIRouter(prefix="/api/v1/libu", tags=["礼部"])


class PolicyAction(BaseModel):
    permission_reference: str = Field(min_length=1)
    disclaimer_version: str = Field(min_length=1)


@router.get("/status")
def status(repository: Annotated[ComplianceRepository, Depends(get_compliance_repository)]):
    records = repository.list_current_records(AssetKind.A_SHARE)
    now = datetime.now(timezone.utc)
    stale = bool(records) and any(now - item.recorded_at > timedelta(days=90) for item in records)
    features = [repository.check_feature_sources("paper_orders", AssetKind.A_SHARE)]
    return {"policy_state": "stale" if stale else "current", "sources": records, "features": features}


def _append(repository, source, payload, state: Literal["authorized", "revoked"], acknowledged):
    now = datetime.now(timezone.utc)
    record = ComplianceRecord(
        record_id=f"compliance-{uuid4().hex}", asset=AssetKind.A_SHARE, source=source,
        permission_state=state, permission_reference=payload.permission_reference,
        disclaimer_version=payload.disclaimer_version,
        user_acknowledged_at=now if acknowledged else None, recorded_at=now,
    )
    repository.append_record(record)
    return record


@router.post("/sources/{source}/authorize", response_model=ComplianceRecord)
def authorize(source: str, payload: PolicyAction, repository: Annotated[ComplianceRepository, Depends(get_compliance_repository)]):
    return _append(repository, source, payload, "authorized", False)


@router.post("/sources/{source}/revoke", response_model=ComplianceRecord)
def revoke(source: str, payload: PolicyAction, repository: Annotated[ComplianceRepository, Depends(get_compliance_repository)]):
    return _append(repository, source, payload, "revoked", False)


@router.post("/sources/{source}/acknowledge", response_model=ComplianceRecord)
def acknowledge(source: str, payload: PolicyAction, repository: Annotated[ComplianceRepository, Depends(get_compliance_repository)]):
    current = repository.get_current_record(source, AssetKind.A_SHARE)
    state = current.permission_state if current is not None else "pending"
    return _append(repository, source, payload, state, True)
