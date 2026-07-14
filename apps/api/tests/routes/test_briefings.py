from datetime import UTC, date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qibao_api.contracts.briefing import BriefingSections, DailyBriefing
from qibao_api.dependencies import get_briefing_repository, get_briefing_workflow
from qibao_api.routes.briefings import router


NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


def report(phase="postclose"):
    return DailyBriefing(
        report_id="briefing-1", trading_date=date(2026, 7, 14), phase=phase,
        generated_at=NOW, window_start=datetime(2026, 7, 14, 1, 25, tzinfo=UTC),
        window_end=datetime(2026, 7, 14, 7, 30, tzinfo=UTC), event_ids=(),
        interpretation_ids=(), input_snapshot_hash="a" * 64,
        sections=BriefingSections(),
    )


class Workflow:
    def run(self, phase, trading_date):
        assert trading_date == date(2026, 7, 14)
        return report(phase)


class Repository:
    def reports(self, **_filters):
        return [report()]


def test_briefing_run_and_query_routes() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_briefing_workflow] = lambda: Workflow()
    app.dependency_overrides[get_briefing_repository] = lambda: Repository()

    with TestClient(app) as client:
        created = client.post("/api/v1/briefings/postclose/2026-07-14/run")
        listed = client.get("/api/v1/briefings?phase=postclose&trading_date=2026-07-14")

    assert created.status_code == 200
    assert created.json()["report_id"] == "briefing-1"
    assert listed.status_code == 200
    assert listed.json()[0]["phase"] == "postclose"


def test_briefing_route_maps_unconfirmed_calendar_to_409() -> None:
    class Closed:
        def run(self, _phase, _trading_date):
            raise ValueError("not a confirmed trading day")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_briefing_workflow] = lambda: Closed()

    response = TestClient(app).post("/api/v1/briefings/premarket/2026-07-14/run")

    assert response.status_code == 409
