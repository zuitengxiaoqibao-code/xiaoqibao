from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from qibao_api.contracts.bars import DailyBar
from qibao_api.dependencies import get_market_data_service
from qibao_api.main import app


class Repository:
    def __init__(self, bars) -> None:
        self.bars = bars

    def latest(self, symbol: str, limit: int):
        return self.bars


class Service:
    def __init__(self, bars) -> None:
        self.repository = Repository(bars)


class UnexpectedRepository:
    def latest(self, symbol: str, limit: int):
        raise AssertionError(f"repository must not receive invalid A-share code {symbol}")


def make_bars() -> list[DailyBar]:
    closes = ["10", "9", "8", "12", "13"]
    return [DailyBar(symbol="600000", trade_date=date(2026, 7, 1) + timedelta(days=index),
        open=Decimal(value), high=Decimal(value) + 1, low=Decimal(value) - 1,
        close=Decimal(value), volume=1000, amount=Decimal("10000"), source="fixture")
        for index, value in enumerate(closes)]


def client_with_bars(bars) -> TestClient:
    app.dependency_overrides[get_market_data_service] = lambda: Service(bars)
    return TestClient(app)


def test_backtest_requires_local_history() -> None:
    with client_with_bars([]) as client:
        response = client.post("/api/v1/a-shares/600000/backtests", json={"fast_window": 2, "slow_window": 3})

    assert response.status_code == 409
    assert "同步" in response.json()["detail"]


def test_backtest_returns_costs_and_equity_curve() -> None:
    with client_with_bars(make_bars()) as client:
        response = client.post("/api/v1/a-shares/600000/backtests", json={"fast_window": 2, "slow_window": 3})

    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy"] == "sma_cross"
    assert "total_cost" in payload
    assert len(payload["equity_curve"]) == 5


@pytest.mark.parametrize("symbol", ["113001", "123001"])
def test_backtest_rejects_bond_code_before_repository_call(symbol: str) -> None:
    service = Service([])
    service.repository = UnexpectedRepository()
    app.dependency_overrides[get_market_data_service] = lambda: service
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/a-shares/{symbol}/backtests",
            json={"fast_window": 2, "slow_window": 3},
        )

    assert response.status_code == 422
