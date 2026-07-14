import json
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from qibao_api.contracts.convertible_bond import ClauseDates, ConvertibleBondContract
from qibao_api.contracts.market import AssetKind, DataQuality
from qibao_api.contracts.risk import ComplianceRecord
from qibao_api.convertible_bonds.models import BondClauseSnapshot, BondQuote
from qibao_api.convertible_bonds.repository import ClauseRepository
from qibao_api.dependencies import get_bond_service, get_compliance_repository
from qibao_api.libu_compliance.repository import ComplianceRepository
from qibao_api.routes.convertible_bonds import router


NOW = datetime(2026, 7, 14, 2, 30, tzinfo=timezone.utc)


class QuoteSource:
    async def fetch(self, code):
        return BondQuote(symbol=code, name="测试转债", price=Decimal("121.50"),
                         previous_close=Decimal("120"), observed_at=NOW, source="tencent",
                         quality=DataQuality.FRESH, raw_identity="quote-1")


class StockSource:
    async def fetch(self, code):
        return type("Quote", (), {"symbol": code, "name": "测试股份", "price": Decimal("10.25"),
                                  "observed_at": NOW, "source": "tencent",
                                  "quality": DataQuality.FRESH})()


class ClauseSource:
    async def fetch(self, code):
        contract = ConvertibleBondContract(
            bond_code=code, linked_stock="600001", conversion_price=Decimal("12.34"),
            maturity=date(2028, 9, 15), remaining_size=Decimal("18.765432"),
            clause_dates=ClauseDates(conversion_start=date(2023, 3, 1)), as_of=NOW,
        )
        raw = json.dumps({"reports": "two", "ordinary_redemption_clause": True}).encode()
        import hashlib
        return BondClauseSnapshot(contract=contract, raw_payload=raw,
            content_hash=hashlib.sha256(raw).hexdigest(), source="eastmoney", fetched_at=NOW,
            parser_version="test-v1")


def authorize(repository, source, asset):
    repository.append_record(ComplianceRecord(
        record_id=f"{asset}-{source}", asset=asset, source=source,
        permission_state="authorized", permission_reference="test", disclaimer_version="2026-07",
        user_acknowledged_at=NOW, recorded_at=NOW,
    ))


def make_client(tmp_path):
    from qibao_api.convertible_bonds.service import ConvertibleBondService
    from qibao_api.convertible_bonds.diagnosis_repository import BondDiagnosisRepository
    engine = create_engine(f"sqlite:///{tmp_path / 'bond.sqlite3'}")
    clauses = ClauseRepository(engine, verifiers={("eastmoney", "test-v1"): lambda raw, code, when: ClauseSourceSnapshot(raw, code, when)})
    clauses.initialize()
    compliance = ComplianceRepository(tmp_path / "compliance.sqlite3")
    compliance.set_feature_sources("bond_quotes", AssetKind.CONVERTIBLE_BOND, ("tencent",))
    compliance.set_feature_sources("bond_clauses", AssetKind.CONVERTIBLE_BOND, ("eastmoney",))
    diagnoses = BondDiagnosisRepository(tmp_path / "diagnoses.sqlite3")
    service = ConvertibleBondService(QuoteSource(), ClauseSource(), StockSource(), clauses, compliance, diagnoses, clock=lambda: NOW)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_bond_service] = lambda: service
    app.dependency_overrides[get_compliance_repository] = lambda: compliance
    return TestClient(app), compliance, clauses


def ClauseSourceSnapshot(raw, code, when):
    # Repository verifier used by this route-level integration fake.
    contract = ConvertibleBondContract(bond_code=code, linked_stock="600001",
        conversion_price=Decimal("12.34"), maturity=date(2028, 9, 15),
        remaining_size=Decimal("18.765432"),
        clause_dates=ClauseDates(conversion_start=date(2023, 3, 1)), as_of=when)
    import hashlib
    return BondClauseSnapshot(contract=contract, raw_payload=raw,
        content_hash=hashlib.sha256(raw).hexdigest(), source="eastmoney", fetched_at=when,
        parser_version="test-v1")


def test_bond_authorization_is_isolated_and_returns_chinese_403(tmp_path):
    client, compliance, _ = make_client(tmp_path)
    authorize(compliance, "tencent", AssetKind.A_SHARE)
    authorize(compliance, "eastmoney", AssetKind.A_SHARE)
    response = client.get("/api/v1/convertible-bonds/113065/diagnosis")
    assert response.status_code == 403
    assert response.json()["detail"] == "可转债数据源尚未授权：tencent"


def test_diagnosis_fetches_and_appends_reproducible_snapshot(tmp_path):
    client, compliance, clauses = make_client(tmp_path)
    authorize(compliance, "tencent", AssetKind.CONVERTIBLE_BOND)
    authorize(compliance, "eastmoney", AssetKind.CONVERTIBLE_BOND)
    response = client.get("/api/v1/convertible-bonds/113065/diagnosis")
    assert response.status_code == 200
    body = response.json()
    assert body["bond"]["code"] == "113065"
    assert body["linked_stock"]["code"] == "600001"
    assert Decimal(body["metrics"]["conversion_value"]) == Decimal("100") / Decimal("12.34") * Decimal("10.25")
    assert Decimal(body["metrics"]["conversion_premium"]) == (Decimal("121.50") - Decimal(body["metrics"]["conversion_value"])) / Decimal(body["metrics"]["conversion_value"])
    assert body["metrics"]["pure_bond_premium"] is None
    assert body["risk"]["unknowns"] == ["pure_bond_value", "turnover_amount"]
    assert body["strong_redemption"]["state"] == "unknown"
    assert body["strong_redemption"]["evidence_fields"] == {}
    assert body["metric_inputs"]["pure_bond_value"] is None
    assert body["metric_inputs"]["bond_quote"]["source"] == "tencent"
    assert body["metric_inputs"]["stock_quote"]["price"] == "10.25"
    assert body["metric_inputs"]["clause_snapshot"]["content_hash"]
    assert len(clauses.snapshots("113065")) == 1

    candidates = client.get("/api/v1/convertible-bonds/candidates")
    assert candidates.status_code == 200
    assert candidates.json()["items"][0]["bond_code"] == "113065"


def test_route_maps_empty_upstream_and_parse_errors_without_500():
    from qibao_api.convertible_bonds.adapters import ClauseDataUnavailable
    class Broken:
        def dashboard(self): return {}
        def candidates(self): return {}
        async def diagnose(self, _): raise ClauseDataUnavailable("empty")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_bond_service] = lambda: Broken()
    response = TestClient(app).get("/api/v1/convertible-bonds/113065/diagnosis")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "clauses_unavailable"


def test_suspended_diagnosis_is_not_a_candidate(tmp_path):
    client, compliance, _ = make_client(tmp_path)
    authorize(compliance, "tencent", AssetKind.CONVERTIBLE_BOND)
    authorize(compliance, "eastmoney", AssetKind.CONVERTIBLE_BOND)
    service = client.app.dependency_overrides[get_bond_service]()
    original = service.quote_source
    class Suspended:
        async def fetch(self, code):
            quote = await original.fetch(code)
            return quote.model_copy(update={"price": None, "suspended": True, "quality": DataQuality.UNAVAILABLE})
    service.quote_source = Suspended()
    assert client.get("/api/v1/convertible-bonds/113065/diagnosis").status_code == 200
    assert client.get("/api/v1/convertible-bonds/candidates").json()["items"] == []
