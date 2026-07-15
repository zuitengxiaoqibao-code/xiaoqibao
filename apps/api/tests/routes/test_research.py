from datetime import date, datetime, timezone
from decimal import Decimal
import sqlite3

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qibao_api.contracts.market import AssetKind, DataQuality
from qibao_api.contracts.research import Evidence, ResearchCard
from qibao_api.a_shares.diagnosis import (
    AShareDiagnosis,
    DiagnosisSection,
    DiagnosisUnavailableError,
)
from qibao_api.a_shares.models import CandidateBoard
from qibao_api.a_shares.instrument_directory import AShareInstrument
from qibao_api.a_shares.repository import AShareResearchStoreError
from qibao_api.dependencies import (
    get_a_share_diagnosis_service,
    get_a_share_instrument_directory,
    get_a_share_quote_source,
    get_pipeline,
    get_server_time,
)
from qibao_api.main import app
from qibao_api.gongbu.tencent_quotes import parse_tencent_quote
from qibao_api.routes.research import router as research_router
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


class UnauthorizedDiagnosisService(FakeDiagnosisService):
    async def diagnose(self, symbol: str, as_of: date) -> AShareDiagnosis:
        raise SourceAuthorizationError("tencent:missing")


class CorruptResearchService(FakeDiagnosisService):
    def candidates(self, as_of: date, limit: int) -> CandidateBoard:
        raise AShareResearchStoreError("database malformed")


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
    assert response.json()["universe_status"] == "empty"


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


def test_a_share_diagnosis_keeps_compliance_denial_explicit() -> None:
    with diagnosis_client(UnauthorizedDiagnosisService()) as client:
        response = client.get("/api/v1/a-shares/600000/diagnosis?as_of=2026-07-14")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "source_authorization_required"


def test_a_share_store_corruption_maps_to_503() -> None:
    with diagnosis_client(CorruptResearchService()) as client:
        response = client.get("/api/v1/a-shares/candidates?as_of=2026-07-14")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "a_share_research_store_error"


def test_future_research_cutoff_is_rejected() -> None:
    with diagnosis_client() as client:
        response = client.get("/api/v1/a-shares/candidates?as_of=2999-01-01")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "future_as_of_not_allowed"


SEARCH_NOW = datetime(2026, 7, 15, 2, 0, tzinfo=timezone.utc)


class SearchDirectory:
    def __init__(self) -> None:
        self.items = {
            "000001": AShareInstrument(
                symbol="000001", name="平安银行", exchange="sz",
                observed_at=SEARCH_NOW, quote_quality="ready",
            ),
            "600000": AShareInstrument(
                symbol="600000", name="浦发银行", exchange="sh",
                observed_at=SEARCH_NOW, quote_quality="ready",
            ),
        }

    def search(self, query: str, limit: int = 10):
        normalized = query.strip().casefold()
        matches = [
            item for item in self.items.values()
            if normalized in item.symbol or normalized in item.name.casefold()
        ]
        return tuple(sorted(matches, key=lambda item: item.symbol)[:limit])

    def resolve(self, symbol: str):
        return self.items.get(symbol)

    def observe(self, item: AShareInstrument) -> None:
        self.items[item.symbol] = item


class NeverQuoteSource:
    async def fetch(self, symbol: str):
        request = httpx.Request("GET", "https://qt.gtimg.cn")
        raise httpx.ConnectError(f"unavailable {symbol}", request=request)


class QuoteSource:
    async def fetch(self, symbol: str):
        return type("Quote", (), {
            "symbol": symbol,
            "name": "邯郸钢铁",
            "observed_at": datetime(2026, 7, 15, 10, 1),
            "quality": DataQuality.FRESH,
        })()


class MismatchedQuoteSource:
    async def fetch(self, symbol: str):
        return type("Quote", (), {
            "symbol": "600002",
            "name": "错误标的",
            "observed_at": SEARCH_NOW,
            "quality": DataQuality.FRESH,
        })()


class ProgrammingErrorQuoteSource:
    async def fetch(self, symbol: str):
        raise sqlite3.ProgrammingError("closed database")


class MalformedNumericQuoteSource:
    async def fetch(self, symbol: str):
        fields = [""] * 50
        fields[1:5] = ["坏行情", symbol, "not-a-number", "10.00"]
        fields[30] = "20260715100100"
        return parse_tencent_quote("~".join(fields), source="tencent")


def search_client(directory=None, source=None) -> TestClient:
    application = FastAPI()
    application.include_router(research_router)
    application.dependency_overrides[get_a_share_instrument_directory] = lambda: (
        directory or SearchDirectory()
    )
    application.dependency_overrides[get_a_share_quote_source] = lambda: (
        source or NeverQuoteSource()
    )
    application.dependency_overrides[get_server_time] = lambda: SEARCH_NOW
    return TestClient(application)


def test_search_returns_only_a_shares_in_rank_order() -> None:
    response = search_client().get("/api/v1/a-shares/search?q=银行&limit=10")

    assert response.status_code == 200
    assert [item["symbol"] for item in response.json()["items"]] == ["000001", "600000"]
    assert all(item["asset"] == "a_share" for item in response.json()["items"])
    assert response.json()["query"] == "银行"
    assert response.json()["server_time"] == "2026-07-15T02:00:00Z"


def test_search_returns_empty_items_without_guessing() -> None:
    response = search_client().get("/api/v1/a-shares/search?q=不存在名称")

    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.parametrize("query", ["", "   "])
def test_search_rejects_empty_query(query: str) -> None:
    response = search_client().get("/api/v1/a-shares/search", params={"q": query})

    assert response.status_code == 422


def test_exact_code_source_failure_returns_unavailable_instead_of_500() -> None:
    response = search_client(directory=SearchDirectory()).get(
        "/api/v1/a-shares/search?q=600001"
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["source_status"] == "unavailable"


def test_code_only_local_observation_still_requires_quote_verification() -> None:
    directory = SearchDirectory()
    directory.items["600001"] = AShareInstrument(
        symbol="600001", name="600001", exchange="sh",
        observed_at=SEARCH_NOW, quote_quality="unavailable",
    )

    response = search_client(directory=directory).get(
        "/api/v1/a-shares/search?q=600001"
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["source_status"] == "unavailable"


def test_exact_code_is_verified_and_observed() -> None:
    directory = SearchDirectory()
    response = search_client(directory=directory, source=QuoteSource()).get(
        "/api/v1/a-shares/search?q=600001"
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["symbol"] == "600001"
    assert response.json()["items"][0]["name"] == "邯郸钢铁"
    assert directory.resolve("600001") is not None


def test_exact_code_rejects_mismatched_upstream_symbol() -> None:
    directory = SearchDirectory()
    response = search_client(directory=directory, source=MismatchedQuoteSource()).get(
        "/api/v1/a-shares/search?q=600001"
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["source_status"] == "unavailable"
    assert directory.resolve("600002") is None


def test_exact_code_does_not_hide_programming_or_storage_errors() -> None:
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        search_client(source=ProgrammingErrorQuoteSource()).get(
            "/api/v1/a-shares/search?q=600001"
        )


def test_exact_code_maps_malformed_tencent_numeric_payload_to_unavailable() -> None:
    response = search_client(source=MalformedNumericQuoteSource()).get(
        "/api/v1/a-shares/search?q=600001"
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["source_status"] == "unavailable"
