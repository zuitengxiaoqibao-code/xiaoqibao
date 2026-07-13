from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import ComplianceRecord
from qibao_api.dependencies import (
    get_audit_repository,
    get_compliance_repository,
    get_paper_repository,
)
from qibao_api.dongchang.repository import AuditFindingRepository
from qibao_api.hubu.repository import PaperRepository
from qibao_api.libu_compliance.repository import ComplianceRepository
from qibao_api.routes.dongchang import router as dongchang_router
from qibao_api.routes.libu import router as libu_router
from qibao_api.routes.xingbu import router as xingbu_router


NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


def make_client(tmp_path):
    paper = PaperRepository(tmp_path / "paper.sqlite3")
    compliance = ComplianceRepository(tmp_path / "compliance.sqlite3")
    audit = AuditFindingRepository(tmp_path / "audit.sqlite3")
    compliance.set_feature_sources("paper_orders", AssetKind.A_SHARE, ("tencent",))
    application = FastAPI()
    application.include_router(xingbu_router)
    application.include_router(libu_router)
    application.include_router(dongchang_router)
    application.dependency_overrides[get_paper_repository] = lambda: paper
    application.dependency_overrides[get_compliance_repository] = lambda: compliance
    application.dependency_overrides[get_audit_repository] = lambda: audit
    return TestClient(application), compliance, audit


def test_dedicated_status_routes_handle_empty_audit_and_stale_policy(tmp_path) -> None:
    client, compliance, _ = make_client(tmp_path)
    compliance.append_record(ComplianceRecord(
        record_id="old", asset=AssetKind.A_SHARE, source="tencent",
        permission_state="authorized", permission_reference="operator:test",
        disclaimer_version="2026-01", user_acknowledged_at=NOW,
        recorded_at=NOW - timedelta(days=200),
    ))

    risk = client.get("/api/v1/xingbu/status")
    policy = client.get("/api/v1/libu/status")
    audit = client.get("/api/v1/dongchang/findings")

    assert risk.status_code == 200
    assert risk.json()["rule_version"]
    assert policy.json()["policy_state"] == "stale"
    assert policy.json()["features"][0]["allowed"] is True
    assert audit.json() == {"state": "ready", "findings": []}


def test_libu_explicit_revoke_and_acknowledge_actions(tmp_path) -> None:
    client, _, _ = make_client(tmp_path)

    revoked = client.post("/api/v1/libu/sources/tencent/revoke", json={
        "permission_reference": "operator:revoked", "disclaimer_version": "2026-07"
    })
    assert revoked.status_code == 200
    assert revoked.json()["permission_state"] == "revoked"
    assert client.get("/api/v1/libu/status").json()["features"][0]["allowed"] is False

    authorized = client.post("/api/v1/libu/sources/tencent/authorize", json={
        "permission_reference": "contract:local-test", "disclaimer_version": "2026-07"
    })
    assert authorized.json()["user_acknowledged_at"] is None
    assert client.get("/api/v1/libu/status").json()["features"][0]["allowed"] is False

    acknowledged = client.post("/api/v1/libu/sources/tencent/acknowledge", json={
        "permission_reference": "contract:local-test", "disclaimer_version": "2026-07"
    })
    assert acknowledged.json()["user_acknowledged_at"] is not None
    assert client.get("/api/v1/libu/status").json()["features"][0]["allowed"] is True


def test_audit_store_unavailable_is_explicit() -> None:
    class BrokenAudit:
        def list_findings(self, *, asset):
            raise RuntimeError("offline")

    application = FastAPI()
    application.include_router(dongchang_router)
    application.dependency_overrides[get_audit_repository] = lambda: BrokenAudit()

    response = TestClient(application).get("/api/v1/dongchang/findings")

    assert response.status_code == 503
    assert response.json()["detail"] == "audit_store_unavailable"
