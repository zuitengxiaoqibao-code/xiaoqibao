from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from qibao_api.bingbu.paper_broker import PaperOrderResult
from qibao_api.contracts.trading import Fill, OrderRequest
from qibao_api.dependencies import get_paper_repository, get_paper_service
from qibao_api.hubu.repository import PaperRepository
from qibao_api.main import app


class FakePaperService:
    async def submit(self, account_id: str, request: OrderRequest) -> PaperOrderResult:
        return PaperOrderResult(
            order_id="order-1",
            status="filled",
            fill=Fill(
                fill_id="fill-1",
                order_id="order-1",
                symbol=request.symbol,
                side=request.side,
                shares=request.shares,
                price=Decimal("10"),
                gross_amount=Decimal("1000"),
                commission=Decimal("5"),
                slippage=Decimal("0"),
                quote_source="tencent",
                quote_observed_at=datetime(2026, 7, 13, 10, 30),
                risk_decision_id="risk-1",
                filled_at=datetime(2026, 7, 13, 10, 30, 1),
            ),
        )


def make_client(tmp_path) -> TestClient:
    repository = PaperRepository(tmp_path / "paper.sqlite3")
    app.dependency_overrides[get_paper_repository] = lambda: repository
    app.dependency_overrides[get_paper_service] = lambda: FakePaperService()
    return TestClient(app)


def test_create_account_and_read_empty_portfolio(tmp_path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/api/v1/paper/accounts",
            json={"account_id": "paper-1", "initial_cash": "100000"},
        )
        positions = client.get("/api/v1/paper/accounts/paper-1/positions")
        ledger = client.get("/api/v1/paper/accounts/paper-1/ledger")

    assert created.status_code == 201
    assert created.json()["cash"] == "100000"
    assert positions.json() == []
    assert ledger.json()[0]["reason"] == "deposit"


def test_submit_order_returns_fill_evidence(tmp_path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/api/v1/paper/accounts",
            json={"account_id": "paper-1", "initial_cash": "100000"},
        )
        response = client.post(
            "/api/v1/paper/accounts/paper-1/orders",
            json={
                "client_order_id": "client-1",
                "symbol": "600000",
                "side": "buy",
                "shares": 100,
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "filled"
    assert response.json()["fill"]["quote_source"] == "tencent"
