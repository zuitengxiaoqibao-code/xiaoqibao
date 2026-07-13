from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from qibao_api.contracts.market import AssetKind
from qibao_api.dependencies import get_audit_repository
from qibao_api.dongchang.repository import AuditFindingRepository
from qibao_api.dongchang.models import AuditInput
from qibao_api.dongchang.audit import AuditEngine


router = APIRouter(prefix="/api/v1/dongchang", tags=["东厂"])


@router.post("/audit-runs", status_code=status.HTTP_201_CREATED)
def run_audit(payload: AuditInput, repository: Annotated[AuditFindingRepository, Depends(get_audit_repository)]):
    findings = AuditEngine().audit(payload)
    repository.append_audit(payload, findings)
    return {"audit_run_id": payload.audit_run_id, "findings": findings}


@router.get("/findings")
def findings(repository: Annotated[AuditFindingRepository, Depends(get_audit_repository)]):
    try:
        items = repository.list_findings(asset=AssetKind.A_SHARE)
        result = []
        for item in items:
            result.append({
                **item.model_dump(mode="json"),
                "snapshots": [
                    repository.get_snapshot(snapshot_id).snapshot.model_dump(mode="json")
                    for snapshot_id in item.input_snapshot_ids
                ],
            })
        return {"state": "ready", "findings": result}
    except Exception as error:
        raise HTTPException(status_code=503, detail="audit_store_unavailable") from error
