import re
import threading
from datetime import date, datetime, time, timedelta, timezone


CHINA_TZ = timezone(timedelta(hours=8))
SCHEDULE = (
    ("premarket", "0920", time(9, 20)),
    ("intraday", "1030", time(10, 30)),
    ("intraday", "1330", time(13, 30)),
    ("intraday", "1430", time(14, 30)),
    ("postclose", "1530", time(15, 30)),
)


class DailyBriefingScheduler:
    def __init__(
        self, workflow, calendar, repository, *,
        max_attempts: int = 3, catchup_days: int = 7, decision_workflow=None,
        intraday_monitor=None,
    ) -> None:
        self.workflow = workflow
        self.calendar = calendar
        self.repository = repository
        self.max_attempts = max_attempts
        self.catchup_days = catchup_days
        self.decision_workflow = decision_workflow
        self.intraday_monitor = intraday_monitor
        self._run_lock = threading.RLock()

    def tick(self, now: datetime) -> None:
        with self._run_lock:
            local_now = now.astimezone(CHINA_TZ)
            if self.repository.paused():
                return
            for days_ago in range(self.catchup_days, -1, -1):
                trading_date = local_now.date() - timedelta(days=days_ago)
                if not self.calendar.is_trading_day(trading_date):
                    continue
                for phase, slot, scheduled_time in SCHEDULE:
                    scheduled_at = datetime.combine(trading_date, scheduled_time, CHINA_TZ)
                    if local_now >= scheduled_at:
                        self._run(
                            phase, trading_date, slot,
                            workflow_now=scheduled_at,
                            occurred_at=now,
                            trigger="scheduled",
                        )
                        if phase == "intraday" and self.intraday_monitor is not None:
                            self._run_monitor(
                                trading_date, slot, scheduled_at, now, "scheduled"
                            )

    def tick_intraday(self, now: datetime):
        if self.intraday_monitor is None or self.repository.paused():
            return None
        local_now = now.astimezone(CHINA_TZ)
        slot = local_now.strftime("%H%M%S")
        with self._run_lock:
            return self._run_monitor(local_now.date(), slot, now, now, "background")

    def run_manual(
        self, phase: str, trading_date: date, now: datetime
    ):
        slot = f"manual-{now.astimezone(CHINA_TZ).strftime('%H%M%S')}"
        with self._run_lock:
            return self._run(
                phase, trading_date, slot,
                workflow_now=now,
                occurred_at=now,
                trigger="manual",
                force=True,
            )

    def set_paused(self, paused: bool, now: datetime) -> None:
        self.repository.set_paused(paused, now)

    def status(self) -> dict:
        return {"paused": self.repository.paused(), "jobs": self.repository.jobs()}

    def _run(
        self, phase: str, trading_date: date, slot: str, *,
        workflow_now: datetime, occurred_at: datetime, trigger: str,
        force: bool = False,
    ):
        job_key = f"{trading_date.isoformat()}:{phase}:{slot}"
        events = self.repository.attempts_for(job_key)
        attempt_count = max((item["attempt"] for item in events), default=0)
        if events and events[-1]["status"] == "started":
            report = self._persisted_report(phase, trading_date, workflow_now)
            if report is not None:
                self.repository.append_attempt(
                    job_key=job_key, phase=phase, trading_date=trading_date,
                    slot=slot, trigger=trigger, attempt=attempt_count,
                    status="completed", occurred_at=occurred_at,
                    report_id=report.report_id,
                )
                return report
        if not force and (
            any(item["status"] == "completed" for item in events)
            or attempt_count >= self.max_attempts
        ):
            return None
        attempt = attempt_count + 1
        self.repository.append_attempt(
            job_key=job_key, phase=phase, trading_date=trading_date,
            slot=slot, trigger=trigger, attempt=attempt, status="started",
            occurred_at=occurred_at,
        )
        try:
            report = self.workflow.run(phase, trading_date, now=workflow_now)
        except Exception as error:
            self.repository.append_attempt(
                job_key=job_key, phase=phase, trading_date=trading_date,
                slot=slot, trigger=trigger, attempt=attempt, status="failed",
                occurred_at=occurred_at, error_code=_error_code(error),
            )
            return None
        self.repository.append_attempt(
            job_key=job_key, phase=phase, trading_date=trading_date,
            slot=slot, trigger=trigger, attempt=attempt, status="completed",
            occurred_at=occurred_at, report_id=report.report_id,
        )
        if phase == "premarket" and self.decision_workflow is not None:
            decision_job_key = f"{job_key}:decision"
            self.repository.append_attempt(
                job_key=decision_job_key, phase=phase, trading_date=trading_date,
                slot=f"{slot}:decision", trigger=trigger, attempt=attempt,
                status="started", occurred_at=occurred_at,
            )
            try:
                decision = self.decision_workflow.run(
                    "premarket", trading_date, now=workflow_now
                )
            except Exception as error:
                self.repository.append_attempt(
                    job_key=decision_job_key, phase=phase, trading_date=trading_date,
                    slot=f"{slot}:decision", trigger=trigger, attempt=attempt,
                    status="failed", occurred_at=occurred_at,
                    error_code=_error_code(error),
                )
            else:
                snapshot = getattr(decision, "snapshot", None)
                self.repository.append_attempt(
                    job_key=decision_job_key, phase=phase, trading_date=trading_date,
                    slot=f"{slot}:decision", trigger=trigger, attempt=attempt,
                    status="completed", occurred_at=occurred_at,
                    report_id=getattr(snapshot, "snapshot_id", None),
                )
        return report

    def _persisted_report(
        self, phase: str, trading_date: date, generated_at: datetime
    ):
        repository = getattr(self.workflow, "briefing_repository", None)
        if repository is None:
            return None
        return next((
            report for report in repository.reports(
                phase=phase, trading_date=trading_date
            )
            if report.generated_at == generated_at
        ), None)

    def _run_monitor(self, trading_date, slot, workflow_now, occurred_at, trigger):
        job_key = f"{trading_date.isoformat()}:monitor:{slot}"
        if trigger == "scheduled":
            job_key = f"{trading_date.isoformat()}:intraday:{slot}:monitor"
        events = self.repository.attempts_for(job_key)
        if any(item["status"] == "completed" for item in events):
            return None
        attempt = max((item["attempt"] for item in events), default=0) + 1
        values = dict(
            job_key=job_key, phase="intraday_monitor", trading_date=trading_date,
            slot=f"{slot}:monitor", trigger=trigger, attempt=attempt,
            occurred_at=occurred_at,
        )
        self.repository.append_attempt(**values, status="started")
        try:
            result = self.intraday_monitor.check(workflow_now)
        except Exception as error:
            self.repository.append_attempt(
                **values, status="failed", error_code=_error_code(error)
            )
            return None
        self.repository.append_attempt(
            **values, status="completed", report_id=getattr(result, "result_id", None)
        )
        return result


def _error_code(error: Exception) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", error.__class__.__name__).lower()
