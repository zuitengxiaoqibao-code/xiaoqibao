from datetime import UTC, date, datetime, timedelta, timezone

from qibao_api.shangshu.operations_repository import OperationsRepository
from qibao_api.shangshu.scheduler import DailyBriefingScheduler


TRADE_DATE = date(2026, 7, 14)


class Calendar:
    def is_trading_day(self, value):
        return value == TRADE_DATE


class Workflow:
    def __init__(self):
        self.calls = []
        self.failures = 0
        self.briefing_repository = type("Reports", (), {"reports": lambda _self, **_filters: []})()

    def run(self, phase, trading_date, *, now):
        self.calls.append((phase, trading_date, now))
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary failure")
        return type("Report", (), {"report_id": f"report-{phase}-{len(self.calls)}"})()


class DecisionWorkflow:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    def run(self, phase, trading_date, *, now):
        self.calls.append((phase, trading_date, now))
        if self.fail:
            raise RuntimeError("decision failure")


def test_scheduler_runs_due_slots_once_and_survives_restart(tmp_path) -> None:
    repository = OperationsRepository(tmp_path / "operations.sqlite3")
    workflow = Workflow()
    scheduler = DailyBriefingScheduler(workflow, Calendar(), repository)
    now = datetime(2026, 7, 14, 2, 31, tzinfo=UTC)

    scheduler.tick(now)
    scheduler.tick(now)
    repository.close()

    reopened = OperationsRepository(tmp_path / "operations.sqlite3")
    DailyBriefingScheduler(workflow, Calendar(), reopened).tick(now)

    assert [call[0] for call in workflow.calls] == ["premarket", "intraday"]
    assert [item["status"] for item in reopened.jobs()] == ["completed", "completed"]
    reopened.close()


def test_scheduler_retries_failure_three_times_then_stops(tmp_path) -> None:
    repository = OperationsRepository(tmp_path / "operations.sqlite3")
    workflow = Workflow()
    workflow.failures = 5
    scheduler = DailyBriefingScheduler(workflow, Calendar(), repository, max_attempts=3)
    now = datetime(2026, 7, 14, 1, 21, tzinfo=UTC)

    for _ in range(5):
        scheduler.tick(now)

    job = repository.jobs()[0]
    assert len(workflow.calls) == 3
    assert job["status"] == "failed"
    assert job["attempts"] == 3
    assert job["error_code"] == "runtime_error"
    assert job["occurred_at"] == now.isoformat()
    repository.close()


def test_paused_scheduler_persists_and_manual_run_is_audited(tmp_path) -> None:
    database = tmp_path / "operations.sqlite3"
    repository = OperationsRepository(database)
    workflow = Workflow()
    scheduler = DailyBriefingScheduler(workflow, Calendar(), repository)
    scheduler.set_paused(True, datetime(2026, 7, 14, 0, 0, tzinfo=UTC))
    scheduler.tick(datetime(2026, 7, 14, 8, 0, tzinfo=UTC))
    repository.close()

    reopened = OperationsRepository(database)
    restarted = DailyBriefingScheduler(workflow, Calendar(), reopened)
    assert restarted.status()["paused"] is True
    restarted.run_manual("postclose", TRADE_DATE, datetime(2026, 7, 14, 8, 1, tzinfo=UTC))

    assert len(workflow.calls) == 1
    assert reopened.jobs()[0]["trigger"] == "manual"
    reopened.close()


def test_scheduler_reconciles_report_after_crash_before_completion_log(tmp_path) -> None:
    repository = OperationsRepository(tmp_path / "operations.sqlite3")
    workflow = Workflow()
    scheduled = datetime(2026, 7, 14, 1, 20, tzinfo=UTC)
    report = type("Report", (), {
        "report_id": "report-already-persisted", "generated_at": scheduled,
    })()
    workflow.briefing_repository = type(
        "Reports", (), {"reports": lambda _self, **_filters: [report]}
    )()
    repository.append_attempt(
        job_key="2026-07-14:premarket:0920", phase="premarket",
        trading_date=TRADE_DATE, slot="0920", trigger="scheduled", attempt=1,
        status="started", occurred_at=scheduled,
    )

    DailyBriefingScheduler(workflow, Calendar(), repository).tick(
        datetime(2026, 7, 14, 1, 21, tzinfo=UTC)
    )

    assert workflow.calls == []
    assert repository.jobs()[0]["status"] == "completed"
    assert repository.jobs()[0]["report_id"] == "report-already-persisted"
    repository.close()


def test_scheduler_catches_up_previous_trading_day_after_midnight(tmp_path) -> None:
    repository = OperationsRepository(tmp_path / "operations.sqlite3")
    workflow = Workflow()
    scheduler = DailyBriefingScheduler(workflow, Calendar(), repository)

    scheduler.tick(datetime(2026, 7, 14, 16, 5, tzinfo=UTC))

    assert [call[0] for call in workflow.calls] == [
        "premarket", "intraday", "intraday", "intraday", "postclose"
    ]
    repository.close()


def test_scheduler_runs_optional_decision_workflow_after_successful_premarket(tmp_path) -> None:
    repository = OperationsRepository(tmp_path / "operations.sqlite3")
    workflow = Workflow()
    decisions = DecisionWorkflow()
    scheduler = DailyBriefingScheduler(
        workflow, Calendar(), repository, decision_workflow=decisions,
    )
    now = datetime(2026, 7, 14, 1, 21, tzinfo=UTC)
    scheduler.tick(now)
    assert decisions.calls == [("premarket", TRADE_DATE, datetime(2026, 7, 14, 9, 20, tzinfo=timezone(timedelta(hours=8))))]
    jobs = {item["job_key"]: item for item in repository.jobs()}
    assert jobs["2026-07-14:premarket:0920"]["status"] == "completed"
    assert jobs["2026-07-14:premarket:0920:decision"]["status"] == "completed"
    assert [item["status"] for item in repository.attempts_for(
        "2026-07-14:premarket:0920:decision"
    )] == ["started", "completed"]
    repository.close()


def test_decision_failure_does_not_overwrite_briefing_completion(tmp_path) -> None:
    repository = OperationsRepository(tmp_path / "operations.sqlite3")
    scheduler = DailyBriefingScheduler(
        Workflow(), Calendar(), repository, decision_workflow=DecisionWorkflow(fail=True),
    )
    scheduler.tick(datetime(2026, 7, 14, 1, 21, tzinfo=UTC))
    briefing = repository.attempts_for("2026-07-14:premarket:0920")
    decision = repository.attempts_for("2026-07-14:premarket:0920:decision")
    assert [item["status"] for item in briefing] == ["started", "completed"]
    assert [item["status"] for item in decision] == ["started", "failed"]
    assert decision[-1]["error_code"] == "runtime_error"
    jobs = {item["job_key"]: item for item in repository.jobs()}
    assert jobs["2026-07-14:premarket:0920"]["status"] == "completed"
    assert jobs["2026-07-14:premarket:0920:decision"]["status"] == "failed"
    repository.close()
