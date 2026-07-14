from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from qibao_api.contracts.bars import DataSourceState, SyncReport
from qibao_api.dependencies import get_market_data_service
from qibao_api.main import app


class FakeRepository:
    def latest(self, symbol: str, limit: int):
        return []


class FakeMarketDataService:
    repository = FakeRepository()

    def sync_symbol(self, symbol: str, limit: int) -> SyncReport:
        return SyncReport(
            symbol=symbol,
            state=DataSourceState.READY,
            written_rows=limit,
            source="baidu",
            parquet_path=f"{symbol}.parquet",
            started_at=datetime(2026, 7, 13, 14, 0),
            finished_at=datetime(2026, 7, 13, 14, 1),
            message="同步完成",
        )


class UnexpectedRepository:
    def latest(self, symbol: str, limit: int):
        raise AssertionError(f"repository must not receive invalid A-share code {symbol}")


class UnexpectedMarketDataService:
    repository = UnexpectedRepository()

    def sync_symbol(self, symbol: str, limit: int) -> SyncReport:
        raise AssertionError(f"service must not receive invalid A-share code {symbol}")


def make_client() -> TestClient:
    app.dependency_overrides[get_market_data_service] = lambda: FakeMarketDataService()
    return TestClient(app)


def test_sync_endpoint_returns_actual_source() -> None:
    with make_client() as client:
        response = client.post("/api/v1/a-shares/600000/history/sync?limit=20")

    assert response.status_code == 200
    assert response.json()["source"] == "baidu"
    assert response.json()["written_rows"] == 20


def test_history_endpoint_returns_empty_list_before_sync() -> None:
    with make_client() as client:
        response = client.get("/api/v1/a-shares/600000/history?limit=20")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("symbol", ["113001", "123001"])
@pytest.mark.parametrize(
    ("method", "suffix"),
    [("post", "/history/sync"), ("get", "/history")],
)
def test_history_routes_reject_bond_code_before_downstream_call(
    symbol: str, method: str, suffix: str
) -> None:
    app.dependency_overrides[get_market_data_service] = lambda: UnexpectedMarketDataService()
    with TestClient(app) as client:
        response = getattr(client, method)(f"/api/v1/a-shares/{symbol}{suffix}")

    assert response.status_code == 422
