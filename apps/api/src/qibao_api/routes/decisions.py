from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from qibao_api.dependencies import (
    get_decision_calendar,
    get_decision_poll_state,
    get_decision_repository,
    get_scheduler,
    get_server_time,
)
from qibao_api.shangshu.decision_repository import DecisionIntegrityError
from qibao_api.shangshu.phase_lifecycle import resolve_phase_execution


router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])
CHINA_TZ = timezone(timedelta(hours=8))
PHASES = ("premarket", "intraday", "postclose")


def _phase(now: datetime) -> Literal["premarket", "intraday", "postclose"]:
    local = now.astimezone(CHINA_TZ).time()
    if local < time(9, 25):
        return "premarket"
    if local < time(15):
        return "intraday"
    return "postclose"


def _model_dump(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _slot(
    aggregate, *, materialized_advice=None, change_stream=None, execution=None
):
    if aggregate is None:
        return {
            "phase_status": "empty", "quality": "empty", "aggregate_version": None,
            "ai_status": "not_requested", "advice": [], "evidence": [],
            "execution": _model_dump(execution),
        }
    payload = _model_dump(aggregate)
    snapshot = payload["snapshot"]
    effective_advice = materialized_advice if materialized_advice is not None else payload.get("advice", [])
    evidence = [
        item for advice in effective_advice
        for item in advice.get("supporting_evidence", []) + advice.get("contrary_evidence", [])
    ]
    return {
        "phase_status": snapshot["status"],
        "quality": snapshot["data_quality"],
        "aggregate_version": snapshot["snapshot_id"],
        "strategy_versions": sorted({item["strategy_version"] for item in effective_advice}),
        "ai_status": snapshot["ai_status"],
        "generated_at": snapshot.get("generated_at"),
        "advice": effective_advice,
        "evidence": evidence,
        "delta_version": snapshot["snapshot_id"],
        "delta_advice": payload.get("advice", []),
        "change_stream": change_stream or [],
        "execution": _model_dump(execution),
    }


def _intraday_state(repository, trading_date):
    current = {}
    premarket = repository.latest(trading_date, "premarket")
    if premarket is not None:
        for item in _model_dump(premarket).get("advice", []):
            current[(item["symbol"], item["horizon"])] = item
    cycles = sorted(
        repository.cycles(trading_date, "intraday"),
        key=lambda cycle: _model_dump(cycle)["snapshot"]["sequence"],
    )
    stream = []
    for cycle in cycles:
        payload = _model_dump(cycle)
        snapshot = payload["snapshot"]
        stream.append({
            "snapshot_id": snapshot["snapshot_id"],
            "sequence": snapshot["sequence"],
            "generated_at": snapshot["generated_at"],
            "delta_advice": payload.get("advice", []),
        })
        for item in payload.get("advice", []):
            current[(item["symbol"], item["horizon"])] = item
    return list(current.values()), stream


def _polling(state, server_time, market_session):
    if state is None:
        return {
            "status": "uninitialized", "focus_interval_seconds": None,
            "universe_interval_seconds": None, "next_check_seconds": None,
            "last_focus_success_at": None, "last_universe_success_at": None,
            "consecutive_focus_failures": 0, "consecutive_universe_failures": 0,
            "stale_after_seconds": 180,
        }
    next_due = min(state.next_focus_due_at, state.next_universe_due_at)
    return {
        "status": state.mode,
        "focus_interval_seconds": state.focus_interval_seconds,
        "universe_interval_seconds": state.universe_interval_seconds,
        "next_check_seconds": max(0, int((next_due - server_time).total_seconds())) if market_session == "open" else None,
        "last_focus_success_at": state.last_focus_success_at,
        "last_universe_success_at": state.last_universe_success_at,
        "consecutive_focus_failures": state.consecutive_focus_failures,
        "consecutive_universe_failures": state.consecutive_universe_failures,
        "stale_after_seconds": 180,
    }


def _response(
    repository, trading_date: date, current_phase: str, server_time: datetime,
    market_session: str, poll_state=None, scheduler=None,
):
    try:
        aggregates = {
            phase: repository.latest(trading_date, phase) for phase in PHASES
        }
        scheduler_status = scheduler.status() if scheduler is not None else {}
        jobs = scheduler_status.get("jobs", [])
        executions = {
            phase: resolve_phase_execution(
                phase=phase, trading_date=trading_date, now=server_time,
                aggregate=aggregates[phase], jobs=jobs,
            )
            for phase in PHASES
        }
        slots = {
            phase: _slot(aggregates[phase], execution=executions[phase])
            for phase in PHASES
        }
        latest_intraday = aggregates["intraday"]
        if latest_intraday is not None and hasattr(repository, "cycles"):
            advice, stream = _intraday_state(repository, trading_date)
            slots["intraday"] = _slot(
                latest_intraday, materialized_advice=advice, change_stream=stream,
                execution=executions["intraday"],
            )
    except DecisionIntegrityError:
        raise HTTPException(status_code=503, detail={
            "code": "decision_integrity_error",
            "message": "Decision history failed integrity verification",
        }) from None
    return {
        "server_time": server_time.isoformat(),
        "trading_date": trading_date.isoformat(),
        "current_phase": current_phase,
        "market_session": market_session,
        "phases": slots,
        "polling": _polling(poll_state, server_time, market_session),
    }


@router.get("/current")
def current_decisions(
    repository=Depends(get_decision_repository), calendar=Depends(get_decision_calendar),
    now: datetime = Depends(get_server_time), poll_state=Depends(get_decision_poll_state),
    scheduler=Depends(get_scheduler),
):
    local_now = now.astimezone(CHINA_TZ)
    trading_date = local_now.date()
    if calendar.is_trading_day(trading_date):
        phase = _phase(local_now)
        return _response(repository, trading_date, phase, now, "open" if phase == "intraday" else "closed", poll_state, scheduler)
    for offset in range(1, 367):
        candidate = trading_date - timedelta(days=offset)
        if calendar.is_trading_day(candidate):
            return _response(repository, candidate, "postclose", now, "closed", poll_state, scheduler)
    return _response(repository, trading_date, "postclose", now, "closed", poll_state, scheduler)


@router.get("/{trading_date}")
def decisions_for_date(
    trading_date: date, repository=Depends(get_decision_repository),
    calendar=Depends(get_decision_calendar), now: datetime = Depends(get_server_time),
    poll_state=Depends(get_decision_poll_state),
    scheduler=Depends(get_scheduler),
):
    if trading_date > now.astimezone(CHINA_TZ).date():
        raise HTTPException(status_code=422, detail={"code": "future_trading_date"})
    confirmed = calendar.is_trading_day(trading_date)
    phase = _phase(now) if confirmed and trading_date == now.astimezone(CHINA_TZ).date() else "postclose"
    return _response(repository, trading_date, phase, now, "open" if phase == "intraday" else "closed", poll_state, scheduler)


@router.post("/{phase}/{trading_date}/run")
def run_decision_phase(
    phase: Literal["premarket", "intraday", "postclose"], trading_date: date,
    scheduler=Depends(get_scheduler), calendar=Depends(get_decision_calendar),
    now: datetime = Depends(get_server_time),
):
    if trading_date > now.astimezone(CHINA_TZ).date():
        raise HTTPException(status_code=422, detail={"code": "future_trading_date"})
    if not calendar.is_trading_day(trading_date):
        raise HTTPException(status_code=409, detail={"code": "unconfirmed_trading_day"})
    result = scheduler.run_manual(phase, trading_date, now)
    if result is None or getattr(result, "status", None) == "failed":
        raise HTTPException(status_code=503, detail={
            "code": "decision_run_failed",
            "message": "Decision phase run failed; inspect operations history",
        })
    return {"phase": phase, "trading_date": trading_date, "delegated": True, "result": _model_dump(result)}
