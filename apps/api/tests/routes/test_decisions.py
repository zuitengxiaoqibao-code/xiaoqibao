from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qibao_api.dependencies import (
    get_decision_calendar,
    get_decision_repository,
    get_decision_poll_state,
    get_scheduler,
    get_server_time,
)
from qibao_api.routes.decisions import router
from qibao_api.shangshu.decision_repository import DecisionIntegrityError
from qibao_api.shangshu.intraday_monitor import PollState


CHINA_TZ = timezone(timedelta(hours=8))


class Repository:
    def __init__(self, values=None, *, broken=False):
        self.values = values or {}
        self.broken = broken

    def latest(self, trading_date, phase):
        if self.broken:
            raise DecisionIntegrityError("secret corrupt payload")
        return self.values.get((trading_date, phase))

    def cycles(self, trading_date, phase):
        return self.values.get((trading_date, f"{phase}_cycles"), [])


class Calendar:
    def __init__(self, trading_days):
        self.trading_days = set(trading_days)

    def is_trading_day(self, value):
        return value in self.trading_days


class Scheduler:
    def __init__(self, result=None, *, jobs=(), paused=False):
        self.calls = []
        self.result = result
        self.jobs = list(jobs)
        self.paused = paused

    def status(self):
        return {"paused": self.paused, "jobs": self.jobs}

    def run_manual(self, phase, trading_date, now):
        self.calls.append((phase, trading_date, now))
        return self.result


def client(*, now, repository=None, trading_days=(), scheduler=None, poll_state=None):
    application = FastAPI()
    application.include_router(router)
    scheduler = scheduler or Scheduler({"status": "completed"})
    application.dependency_overrides[get_decision_repository] = lambda: repository or Repository()
    application.dependency_overrides[get_decision_calendar] = lambda: Calendar(trading_days)
    application.dependency_overrides[get_scheduler] = lambda: scheduler
    application.dependency_overrides[get_server_time] = lambda: now
    application.dependency_overrides[get_decision_poll_state] = lambda: poll_state
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


def test_current_exposes_premarket_schedule_before_the_job_is_due():
    now = datetime(2026, 7, 17, 9, 0, tzinfo=CHINA_TZ)
    api, _ = client(now=now, trading_days=(now.date(),))

    body = api.get("/api/v1/decisions/current").json()

    execution = body["phases"]["premarket"]["execution"]
    assert execution["status"] == "scheduled"
    assert execution["scheduled_at"] == "2026-07-17T09:20:00+08:00"
    assert execution["next_scheduled_at"] == "2026-07-17T09:20:00+08:00"


def test_current_distinguishes_overdue_and_failed_phase_jobs():
    day = date(2026, 7, 17)
    failed_job = {
        "job_key": "2026-07-17:intraday:1030:decision",
        "phase": "intraday",
        "trading_date": day.isoformat(),
        "slot": "1030:decision",
        "trigger": "scheduled",
        "attempt": 1,
        "attempts": 1,
        "status": "failed",
        "occurred_at": "2026-07-17T02:30:10+00:00",
        "report_id": None,
        "error_code": "timeout_error",
    }
    api, _ = client(
        now=datetime(2026, 7, 17, 10, 31, tzinfo=CHINA_TZ),
        trading_days=(day,),
        scheduler=Scheduler(jobs=(failed_job,)),
    )

    phases = api.get("/api/v1/decisions/current").json()["phases"]

    assert phases["premarket"]["execution"]["status"] == "overdue"
    assert phases["intraday"]["execution"]["status"] == "failed"
    assert phases["intraday"]["execution"]["error_code"] == "timeout_error"


def test_current_reports_running_phase_job():
    day = date(2026, 7, 17)
    running_job = {
        "job_key": "2026-07-17:premarket:0920:decision",
        "phase": "premarket",
        "trading_date": day.isoformat(),
        "slot": "0920:decision",
        "trigger": "scheduled",
        "attempt": 1,
        "attempts": 1,
        "status": "started",
        "occurred_at": "2026-07-17T01:20:05+00:00",
        "report_id": None,
        "error_code": None,
    }
    api, _ = client(
        now=datetime(2026, 7, 17, 9, 20, 10, tzinfo=CHINA_TZ),
        trading_days=(day,), scheduler=Scheduler(jobs=(running_job,)),
    )

    execution = api.get("/api/v1/decisions/current").json()["phases"]["premarket"]["execution"]

    assert execution["status"] == "running"
    assert execution["last_attempt_at"] == "2026-07-17T01:20:05Z"


def test_old_manual_completion_does_not_hide_a_missed_later_intraday_slot():
    day = date(2026, 7, 17)
    manual_job = {
        "job_key": "2026-07-17:intraday:manual-110000:decision",
        "phase": "intraday",
        "trading_date": day.isoformat(),
        "slot": "manual-110000:decision",
        "trigger": "manual",
        "attempt": 1,
        "attempts": 1,
        "status": "completed",
        "occurred_at": "2026-07-17T03:00:00+00:00",
        "report_id": "intraday-manual",
        "error_code": None,
    }
    api, _ = client(
        now=datetime(2026, 7, 17, 13, 31, tzinfo=CHINA_TZ),
        trading_days=(day,), scheduler=Scheduler(jobs=(manual_job,)),
    )

    execution = api.get("/api/v1/decisions/current").json()["phases"]["intraday"]["execution"]

    assert execution["status"] == "overdue"
    assert execution["last_attempt_at"] is None


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


def test_polling_response_uses_persisted_backoff_and_failure_state():
    now = datetime(2026, 7, 15, 10, 30, tzinfo=CHINA_TZ)
    state = PollState(
        focus_interval_seconds=240, universe_interval_seconds=300,
        consecutive_focus_failures=3, consecutive_universe_failures=4,
        next_focus_due_at=now + timedelta(seconds=240),
        next_universe_due_at=now + timedelta(seconds=300), mode="degraded",
        last_error_code="timeout_error",
    )
    api, _ = client(now=now, trading_days=(now.date(),), poll_state=state)

    polling = api.get("/api/v1/decisions/current").json()["polling"]

    assert polling["status"] == "degraded"
    assert polling["focus_interval_seconds"] == 240
    assert polling["universe_interval_seconds"] == 300
    assert polling["consecutive_focus_failures"] == 3
    assert polling["next_check_seconds"] == 240


def test_date_specific_today_is_closed_when_calendar_does_not_confirm_trading():
    now = datetime(2026, 7, 18, 10, 30, tzinfo=CHINA_TZ)
    api, _ = client(now=now, trading_days=())

    response = api.get(f"/api/v1/decisions/{now.date().isoformat()}")

    assert response.json()["market_session"] == "closed"
    assert response.json()["current_phase"] == "postclose"


def test_intraday_slot_materializes_unchanged_symbols_and_keeps_latest_delta():
    day = date(2026, 7, 15)
    def snapshot(identity, _phase, sequence=1):
        return {
            "snapshot": {"snapshot_id": identity, "sequence": sequence, "generated_at": f"2026-07-15T10:{sequence:02d}:00+08:00", "status": "ready", "data_quality": "ready", "ai_status": "not_requested"},
            "advice": [], "plans": [],
        }
    premarket = snapshot("pre-1", "premarket")
    premarket["advice"] = [
        {"advice_id": "a1", "symbol": "600000", "horizon": "intraday", "action": "observe", "strategy_version": "v1", "supporting_evidence": [], "contrary_evidence": []},
        {"advice_id": "a2", "symbol": "000001", "horizon": "intraday", "action": "observe", "strategy_version": "v1", "supporting_evidence": [{"evidence_id": "pre-evidence"}], "contrary_evidence": []},
    ]
    delta = snapshot("intra-1", "intraday")
    delta["advice"] = [{"advice_id": "a3", "symbol": "600000", "horizon": "intraday", "action": "wait", "strategy_version": "v1", "supporting_evidence": [], "contrary_evidence": []}]
    delta_two = snapshot("intra-2", "intraday", 2)
    delta_two["advice"] = [{"advice_id": "a4", "symbol": "600000", "horizon": "intraday", "action": "observe", "strategy_version": "v1", "supporting_evidence": [], "contrary_evidence": []}]
    repository = Repository({
        (day, "premarket"): premarket, (day, "intraday"): delta_two,
        (day, "intraday_cycles"): [delta, delta_two],
    })
    api, _ = client(now=datetime(2026, 7, 15, 10, 30, tzinfo=CHINA_TZ), repository=repository, trading_days=(day,))

    slot = api.get("/api/v1/decisions/current").json()["phases"]["intraday"]

    assert {(item["symbol"], item["action"]) for item in slot["advice"]} == {("600000", "observe"), ("000001", "observe")}
    assert [item["advice_id"] for item in slot["delta_advice"]] == ["a4"]
    assert slot["delta_version"] == "intra-2"
    assert [item["snapshot_id"] for item in slot["change_stream"]] == ["intra-1", "intra-2"]
    assert [item["sequence"] for item in slot["change_stream"]] == [1, 2]
    assert slot["change_stream"][0]["delta_advice"][0]["advice_id"] == "a3"
    assert {item["evidence_id"] for item in slot["evidence"]} == {"pre-evidence"}
    assert slot["execution"]["status"] == "completed"
