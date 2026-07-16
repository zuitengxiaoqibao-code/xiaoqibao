from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from qibao_api.contracts.decision import DecisionPhase
from qibao_api.shangshu.scheduler import CHINA_TZ, SCHEDULE


PhaseExecutionStatus = Literal[
    "scheduled", "running", "completed", "failed", "overdue"
]


class PhaseExecution(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: PhaseExecutionStatus
    scheduled_at: AwareDatetime
    next_scheduled_at: AwareDatetime | None
    last_completed_at: AwareDatetime | None
    last_attempt_at: AwareDatetime | None
    attempts: int = Field(ge=0)
    error_code: str | None


def _as_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _aggregate_generated_at(aggregate) -> datetime | None:
    if aggregate is None:
        return None
    snapshot = (
        aggregate.snapshot
        if hasattr(aggregate, "snapshot")
        else aggregate.get("snapshot", {})
    )
    value = (
        snapshot.generated_at
        if hasattr(snapshot, "generated_at")
        else snapshot.get("generated_at")
    )
    return _as_datetime(value)


def resolve_phase_execution(
    *,
    phase: DecisionPhase,
    trading_date: date,
    now: datetime,
    aggregate=None,
    jobs=(),
) -> PhaseExecution:
    phase_slots = [
        (slot, datetime.combine(trading_date, scheduled_time, CHINA_TZ))
        for scheduled_phase, slot, scheduled_time in SCHEDULE
        if scheduled_phase == phase
    ]
    scheduled_at = phase_slots[0][1]
    due_slots = [(slot, value) for slot, value in phase_slots if value <= now]
    future_slots = [value for _, value in phase_slots if value > now]
    next_scheduled_at = future_slots[0] if future_slots else None
    aggregate_generated_at = _aggregate_generated_at(aggregate)

    relevant_jobs = [
        item for item in jobs
        if item.get("phase") == phase
        and item.get("trading_date") == trading_date.isoformat()
        and item.get("trigger") in {"scheduled", "manual"}
        and str(item.get("slot", "")).endswith(":decision")
    ]
    if due_slots:
        latest_due_slot, latest_due_at = due_slots[-1]
        slot_jobs = [
            item for item in relevant_jobs
            if str(item.get("slot", "")).startswith(f"{latest_due_slot}:")
            or (
                str(item.get("slot", "")).startswith("manual-")
                and (_as_datetime(item.get("occurred_at")) or scheduled_at)
                >= latest_due_at
            )
        ]
    else:
        slot_jobs = relevant_jobs
    latest_job = max(
        slot_jobs,
        key=lambda item: _as_datetime(item.get("occurred_at")) or scheduled_at,
        default=None,
    )
    last_attempt_at = (
        _as_datetime(latest_job.get("occurred_at")) if latest_job else None
    )
    attempts = int(latest_job.get("attempts", latest_job.get("attempt", 0))) if latest_job else 0

    if latest_job is not None and latest_job.get("status") == "started":
        status: PhaseExecutionStatus = "running"
    elif latest_job is not None and latest_job.get("status") == "failed":
        status = "failed"
    elif latest_job is not None and latest_job.get("status") == "completed":
        status = "completed"
    elif aggregate_generated_at is not None:
        latest_due_at = due_slots[-1][1] if due_slots else None
        status = (
            "completed"
            if (
                latest_due_at is None
                or len(due_slots) == 1
                or aggregate_generated_at >= latest_due_at
            )
            else "overdue"
        )
    elif not due_slots:
        status = "scheduled"
    else:
        status = "overdue"

    return PhaseExecution(
        status=status,
        scheduled_at=scheduled_at,
        next_scheduled_at=next_scheduled_at,
        last_completed_at=aggregate_generated_at,
        last_attempt_at=last_attempt_at,
        attempts=attempts,
        error_code=(latest_job.get("error_code") if latest_job else None),
    )
