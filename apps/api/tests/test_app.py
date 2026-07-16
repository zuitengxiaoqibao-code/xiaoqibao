from datetime import datetime, timezone
from importlib.util import find_spec

from fastapi.testclient import TestClient

from qibao_api.dependencies import (
    get_decision_calendar,
    get_decision_poll_state,
    get_decision_repository,
    get_server_time,
)
from qibao_api.main import app


client = TestClient(app)


def test_paper_routes_are_not_registered():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert not any(
        path.startswith("/api/v1/paper") for path in response.json()["paths"]
    )


def test_decision_responses_do_not_expose_simulation_plans():
    class Repository:
        @staticmethod
        def latest(*_args):
            return None

    class Calendar:
        @staticmethod
        def is_trading_day(_value):
            return True

    app.dependency_overrides[get_decision_repository] = Repository
    app.dependency_overrides[get_decision_calendar] = Calendar
    app.dependency_overrides[get_decision_poll_state] = lambda: None
    app.dependency_overrides[get_server_time] = lambda: datetime(
        2026, 7, 16, 2, 30, tzinfo=timezone.utc
    )
    try:
        body = client.get("/api/v1/decisions/current").json()
    finally:
        app.dependency_overrides.clear()

    assert "plans" not in str(body)
    assert "simulation_plan_id" not in str(body)


def test_paper_only_modules_are_deleted():
    assert find_spec("qibao_api.contracts.trading") is None
    assert find_spec("qibao_api.hubu.schema") is None
    assert find_spec("qibao_api.libu.allocation") is None
