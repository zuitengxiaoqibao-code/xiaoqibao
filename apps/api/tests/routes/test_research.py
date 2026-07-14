from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from qibao_api.contracts.market import AssetKind, DataQuality
from qibao_api.contracts.research import Evidence, ResearchCard
from qibao_api.a_shares.diagnosis import (
    AShareDiagnosis,
    DiagnosisSection,
    DiagnosisUnavailableError,
)
from qibao_api.a_shares.models import CandidateBoard
from qibao_api.dependencies import get_a_share_diagnosis_service, get_pipeline
from qibao_api.main import app
from qibao_api.libu_compliance.repository import SourceAuthorizationError


class FakePipeline:
    async def run(self, symbol: str) -> ResearchCard:
        return ResearchCard(
            symbol=symbol,
            asset=AssetKind.A_SHARE,
            action="observe",
            change_percent=Decimal("1.49"),
            quality=DataQuality.FRESH,
            evidence=[
                Evidence(
                    label="最新价",
                    value="10.25",
                    source="tencent",
                    observed_at=datetime(2026, 7, 13, 10, 30),
                )
            ],
        )


class UnexpectedPipeline:
    async def run(self, symbol: str) -> ResearchCard:
        raise AssertionError(f"pipeline must not receive invalid A-share code {symbol}")


def make_client() -> TestClient:
    app.dependency_overrides[get_pipeline] = lambda: FakePipeline()
    return TestClient(app)


def test_a_share_snapshot_returns_evidence() -> None:
    with make_client() as client:
        response = client.get("/api/v1/a-shares/600000/snapshot")

    assert response.status_code == 200
    assert response.json()["symbol"] == "600000"
    assert response.json()["evidence"][0]["source"] == "tencent"


@pytest.mark.parametrize("symbol", ["113001", "123001"])
def test_convertible_bond_is_not_routed_through_a_share_endpoint(symbol: str) -> None:
    app.dependency_overrides[get_pipeline] = lambda: UnexpectedPipeline()
    with TestClient(app) as client:
        response = client.get(f"/api/v1/a-shares/{symbol}/snapshot")

    assert response.status_code == 422


def test_beijing_stock_exchange_code_reaches_a_share_snapshot() -> None:
    with make_client() as client:
        response = client.get("/api/v1/a-shares/920001/snapshot")

    assert response.status_code == 200
    assert response.json()["symbol"] == "920001"


def test_health_endpoint_reports_ready() -> None:
    with make_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


class BlockedPipeline:
    async def run(self, symbol: str) -> ResearchCard:
        raise SourceAuthorizationError("tencent:missing")


def test_snapshot_explains_missing_compliance_authorization() -> None:
    app.dependency_overrides[get_pipeline] = lambda: BlockedPipeline()
    with TestClient(app) as client:
        response = client.get("/api/v1/a-shares/600000/snapshot")

    assert response.status_code == 403
    assert response.json() == {
        "detail": {
            "code": "source_authorization_required",
            "message": "请先在礼部完成腾讯行情授权并确认免责声明",
        }
    }


class FakeDiagnosisService:
    def candidates(self, as_of: date, limit: int) -> CandidateBoard:
        return CandidateBoard(as_of=as_of, short_term=[], swing=[])

    async def diagnose(self, symbol: str, as_of: date) -> AShareDiagnosis:
        sections = {
            name: DiagnosisSection(
                status="ready", observed_at=as_of, source="fixture",
                metrics={}, explanation="测试诊断分区",
            )
            for name in (
                "market", "price_volume", "trend", "valuation", "fundamentals",
                "events", "industry", "risk",
            )
        }
        return AShareDiagnosis(
            symbol=symbol, as_of=as_of, action="observe", overall_status="ready",
            sections=sections,
        )


class UnavailableDiagnosisService(FakeDiagnosisService):
    async def diagnose(self, symbol: str, as_of: date) -> AShareDiagnosis:
        raise DiagnosisUnavailableError("market and local history are unavailable")


def diagnosis_client(service=None) -> TestClient:
    app.dependency_overrides[get_a_share_diagnosis_service] = lambda: (
        service or FakeDiagnosisService()
    )
    return TestClient(app)


def test_a_share_candidates_return_separate_empty_boards() -> None:
    with diagnosis_client() as client:
        response = client.get("/api/v1/a-shares/candidates?as_of=2026-07-14&limit=20")

    assert response.status_code == 200
    assert response.json()["asset"] == "a_share"
    assert response.json()["as_of"] == "2026-07-14"
    assert response.json()["short_term"] == []
    assert response.json()["swing"] == []
    assert response.json()["factor_version"] == "a-share-factors-v1"


def test_a_share_diagnosis_returns_all_eight_sections() -> None:
    with diagnosis_client() as client:
        response = client.get("/api/v1/a-shares/600000/diagnosis?as_of=2026-07-14")

    assert response.status_code == 200
    assert response.json()["asset"] == "a_share"
    assert set(response.json()["sections"]) == {
        "market", "price_volume", "trend", "valuation", "fundamentals",
        "events", "industry", "risk",
    }


def test_convertible_bond_never_reaches_a_share_diagnosis() -> None:
    with diagnosis_client() as client:
        response = client.get("/api/v1/a-shares/113001/diagnosis")

    assert response.status_code == 422


def test_a_share_diagnosis_maps_missing_core_data_to_503() -> None:
    with diagnosis_client(UnavailableDiagnosisService()) as client:
        response = client.get("/api/v1/a-shares/600000/diagnosis?as_of=2026-07-14")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "a_share_diagnosis_unavailable"
