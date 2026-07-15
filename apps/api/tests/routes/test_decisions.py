from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qibao_api.dependencies import (
    get_decision_calendar,
    get_decision_repository,
    get_scheduler,
    get_server_time,
)
from qibao_api.routes.decisions import _slot, router
from qibao_api.shangshu.decision_repository import DecisionIntegrityError


CHINA_TZ = timezone(timedelta(hours=8))


class Repository:
    def __init__(self, values=None, *, broken=False):
        self.values = values or {}
        self.broken = broken

    def latest(self, trading_date, phase):
        if self.broken:
            raise DecisionIntegrityError("secret corrupt payload")
        return self.values.get((trading_date, phase))


class Calendar:
    def __init__(self, trading_days):
        self.trading_days = set(trading_days)

    def is_trading_day(self, value):
        return value in self.trading_days


class Scheduler:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def run_manual(self, phase, trading_date, now):
        self.calls.append((phase, trading_date, now))
        return self.result


def client(*, now, repository=None, trading_days=(), scheduler=None):
    application = FastAPI()
    application.include_router(router)
    scheduler = scheduler or Scheduler({"status": "completed"})
    application.dependency_overrides[get_decision_repository] = lambda: repository or Repository()
    application.dependency_overrides[get_decision_calendar] = lambda: Calendar(trading_days)
    application.dependency_overrides[get_scheduler] = lambda: scheduler
    application.dependency_overrides[get_server_time] = lambda: now
    return TestClient(application), scheduler


def test_current_returns_explicit_empty_phase_slots():
    now = datetime(2026, 7, 15, 10, 30, tzinfo=CHINA_TZ)
    api, _ = client(now=now, trading_days=(now.date(),))

    response = api.get("/api/v1/decisions/current")

    assert response.status_code == 200
    body = response.json()
    assert body["current_phase"] == "intraday"
    assert body["market_session"] == "open"
    assert body["phases"]["intraday"]["phase_status"] == "empty"
    assert set(body["phases"]) == {"premarket", "intraday", "postclose"}


def test_non_trading_day_uses_most_recent_postclose_snapshot():
    friday = date(2026, 7, 17)
    aggregate = {"snapshot": {"snapshot_id": "postclose-1", "status": "ready", "data_quality": "ready", "ai_status": "not_requested"}, "advice": [], "plans": []}
    api, _ = client(
        now=datetime(2026, 7, 18, 11, tzinfo=CHINA_TZ),
        repository=Repository({(friday, "postclose"): aggregate}),
        trading_days=(friday,),
    )

    response = api.get("/api/v1/decisions/current")

    assert response.status_code == 200
    assert response.json()["trading_date"] == friday.isoformat()
    assert response.json()["market_session"] == "closed"
    assert response.json()["current_phase"] == "postclose"


def test_integrity_failure_is_503_without_payload_leak():
    today = date(2026, 7, 15)
    api, _ = client(now=datetime(2026, 7, 15, 10, tzinfo=CHINA_TZ), repository=Repository(broken=True), trading_days=(today,))

    response = api.get(f"/api/v1/decisions/{today.isoformat()}")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "decision_integrity_error", "message": "Decision history failed integrity verification"}}
    assert "secret" not in response.text


def test_future_date_is_rejected_and_unconfirmed_day_conflicts():
    today = date(2026, 7, 15)
    api, _ = client(now=datetime(2026, 7, 15, 10, tzinfo=CHINA_TZ), trading_days=(today,))
    assert api.get("/api/v1/decisions/2026-07-16").status_code == 422
    assert api.post("/api/v1/decisions/premarket/2026-07-14/run").status_code == 409


def test_manual_run_delegates_to_scheduler_only():
    today = date(2026, 7, 15)
    api, scheduler = client(now=datetime(2026, 7, 15, 10, tzinfo=CHINA_TZ), trading_days=(today,))

    response = api.post(f"/api/v1/decisions/intraday/{today.isoformat()}/run")

    assert response.status_code == 200
    assert scheduler.calls == [("intraday", today, datetime(2026, 7, 15, 10, tzinfo=CHINA_TZ))]


def test_manual_run_failure_is_not_reported_as_delegated_success():
    today = date(2026, 7, 15)
    api, _ = client(
        now=datetime(2026, 7, 15, 10, tzinfo=CHINA_TZ), trading_days=(today,),
        scheduler=Scheduler(None),
    )

    response = api.post(f"/api/v1/decisions/intraday/{today.isoformat()}/run")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "decision_run_failed"


def test_plan_readiness_requires_all_gate_states_and_reciprocal_references():
    advice = {
        "advice_id": "a1", "action": "simulated_plan", "simulation_plan_id": "p1",
        "risk_decision_id": "r1", "strategy_version": "v1",
        "supporting_evidence": [], "contrary_evidence": [],
        "simulation_gate": {
            "quote_state": "ready", "compliance_state": "ready",
            "evidence_state": "blocked", "risk_state": "approve",
            "risk_decision_id": "r1", "compliance_snapshot_id": "c1",
        },
    }
    aggregate = {
        "snapshot": {"snapshot_id": "s1", "status": "partial", "data_quality": "partial", "ai_status": "not_requested"},
        "advice": [advice],
        "plans": [{"plan_id": "p1", "advice_id": "a1", "risk_decision_id": "r1", "compliance_snapshot_id": "c1"}],
    }

    blocked = _slot(aggregate)["plan_readiness"]["a1"]
    advice["simulation_gate"]["evidence_state"] = "ready"
    ready = _slot(aggregate)["plan_readiness"]["a1"]

    assert blocked["ready"] is False
    assert blocked["reasons"] == ["evidence_blocked"]
    assert ready["ready"] is True
