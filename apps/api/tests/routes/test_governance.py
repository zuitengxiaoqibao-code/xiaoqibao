from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.risk import ComplianceRecord
from qibao_api.dependencies import (
    get_audit_repository,
    get_compliance_repository,
)
from qibao_api.dongchang.repository import AuditFindingRepository
from qibao_api.libu_compliance.repository import ComplianceRepository
from qibao_api.routes.dongchang import router as dongchang_router
from qibao_api.routes.libu import router as libu_router
from qibao_api.routes.xingbu import router as xingbu_router


NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


def make_client(tmp_path):
    compliance = ComplianceRepository(tmp_path / "compliance.sqlite3")
    audit = AuditFindingRepository(tmp_path / "audit.sqlite3")
    compliance.set_feature_sources("market_data", AssetKind.A_SHARE, ("tencent",))
    application = FastAPI()
    application.include_router(xingbu_router)
    application.include_router(libu_router)
    application.include_router(dongchang_router)
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


def test_libu_asset_query_and_actions_keep_a_share_and_bond_records_isolated(tmp_path) -> None:
    client, compliance, _ = make_client(tmp_path)
    compliance.set_feature_sources("bond_quotes", AssetKind.CONVERTIBLE_BOND, ("tencent",))

    response = client.post(
        "/api/v1/libu/sources/tencent/authorize?asset=convertible_bond",
        json={"permission_reference": "bond-contract"},
    )
    assert response.status_code == 200
    assert response.json()["asset"] == "convertible_bond"
    assert client.get("/api/v1/libu/status?asset=convertible_bond").json()["sources"][0]["asset"] == "convertible_bond"
    a_share_sources = client.get("/api/v1/libu/status?asset=a_share").json()["sources"]
    assert all(item["permission_state"] == "pending" for item in a_share_sources)

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

    client.post("/api/v1/libu/sources/tencent/revoke", json={"permission_reference": "operator:revoked-again", "disclaimer_version": "2026-08"})
    revoked_ack = client.post("/api/v1/libu/sources/tencent/acknowledge", json={"permission_reference": "operator:ack", "disclaimer_version": "2026-08"})
    assert revoked_ack.json()["permission_state"] == "revoked"
    assert client.get("/api/v1/libu/status").json()["features"][0]["allowed"] is False


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


def test_xingbu_status_exposes_research_risk_limits(tmp_path) -> None:
    client, _, _ = make_client(tmp_path)
    response = client.get("/api/v1/xingbu/status")
    assert response.json()["rule_version"] == "research-risk-v1"
    assert "recent_rejections" not in response.json()


def test_dongchang_audit_run_generates_and_persists_findings(tmp_path) -> None:
    client, _, audit_repository = make_client(tmp_path)
    payload = {
        "audit_run_id": "run-api-1", "asset": "a_share",
        "recommendation": {"snapshot_id": "rec-api", "asset": "a_share", "symbol": "600000", "conclusion": "bullish", "evidence_link": "snapshot://rec-api", "captured_at": "2026-07-13T00:00:00Z"},
        "outcome": {"snapshot_id": "out-api", "asset": "a_share", "symbol": "600000", "conclusion": "bearish", "evidence_link": "snapshot://out-api", "captured_at": "2026-07-14T00:00:00Z"},
    }

    response = client.post("/api/v1/dongchang/audit-runs", json=payload)

    assert response.status_code == 201
    assert response.json()["findings"][0]["finding_type"] == "recommendation_outcome_deviation"
    assert len(audit_repository.list_findings(asset=AssetKind.A_SHARE)) == 1
