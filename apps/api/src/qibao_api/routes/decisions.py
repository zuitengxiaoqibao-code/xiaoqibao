from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from qibao_api.dependencies import (
    get_decision_calendar,
    get_decision_repository,
    get_scheduler,
    get_server_time,
)
from qibao_api.shangshu.decision_repository import DecisionIntegrityError


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


def _slot(aggregate):
    if aggregate is None:
        return {
            "phase_status": "empty", "quality": "empty", "aggregate_version": None,
            "ai_status": "not_requested", "advice": [], "evidence": [], "plans": [],
        }
    payload = _model_dump(aggregate)
    snapshot = payload["snapshot"]
    evidence = [
        item for advice in payload.get("advice", [])
        for item in advice.get("supporting_evidence", []) + advice.get("contrary_evidence", [])
    ]
    return {
        "phase_status": snapshot["status"],
        "quality": snapshot["data_quality"],
        "aggregate_version": snapshot["snapshot_id"],
        "strategy_versions": sorted({item["strategy_version"] for item in payload.get("advice", [])}),
        "ai_status": snapshot["ai_status"],
        "generated_at": snapshot.get("generated_at"),
        "advice": payload.get("advice", []),
        "evidence": evidence,
        "plans": payload.get("plans", []),
    }


def _response(repository, trading_date: date, current_phase: str, server_time: datetime, market_session: str):
    try:
        slots = {phase: _slot(repository.latest(trading_date, phase)) for phase in PHASES}
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
        "polling": {
            "focus_interval_seconds": 60,
            "universe_interval_seconds": 240,
            "stale_after_seconds": 180,
            "next_check_seconds": 60 if market_session == "open" else None,
        },
    }


@router.get("/current")
def current_decisions(
    repository=Depends(get_decision_repository), calendar=Depends(get_decision_calendar),
    now: datetime = Depends(get_server_time),
):
    local_now = now.astimezone(CHINA_TZ)
    trading_date = local_now.date()
    if calendar.is_trading_day(trading_date):
        phase = _phase(local_now)
        return _response(repository, trading_date, phase, now, "open" if phase == "intraday" else "closed")
    for offset in range(1, 367):
        candidate = trading_date - timedelta(days=offset)
        if calendar.is_trading_day(candidate):
            return _response(repository, candidate, "postclose", now, "closed")
    return _response(repository, trading_date, "postclose", now, "closed")


@router.get("/{trading_date}")
def decisions_for_date(
    trading_date: date, repository=Depends(get_decision_repository),
    calendar=Depends(get_decision_calendar), now: datetime = Depends(get_server_time),
):
    if trading_date > now.astimezone(CHINA_TZ).date():
        raise HTTPException(status_code=422, detail={"code": "future_trading_date"})
    phase = _phase(now) if trading_date == now.astimezone(CHINA_TZ).date() else "postclose"
    return _response(repository, trading_date, phase, now, "open" if phase == "intraday" else "closed")


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
    return {"phase": phase, "trading_date": trading_date, "delegated": True, "result": _model_dump(result)}
