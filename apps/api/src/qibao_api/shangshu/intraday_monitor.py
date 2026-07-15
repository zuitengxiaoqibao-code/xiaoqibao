import json
import hashlib
import re
import sqlite3
import threading
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from qibao_api.contracts.instruments import validate_a_share_code
from qibao_api.contracts.decision import AdviceCard


CHINA_TZ = timezone(timedelta(hours=8))
Scope = Literal["focus", "universe"]
BACKOFF = (60, 120, 240, 300)


class AdviceChangeDetector:
    _FIELDS = (
        "action", "conclusion", "risks", "invalidation_conditions",
        "membership", "simulation_plan",
    )

    @classmethod
    def changed(cls, previous: AdviceCard, proposed: AdviceCard) -> AdviceCard | None:
        differences = []
        for field in cls._FIELDS:
            if cls._value(previous, field) != cls._value(proposed, field):
                differences.append(field)
        if not differences:
            return None
        return proposed.model_copy(update={
            "previous_advice_id": previous.advice_id,
            "changed_fields": tuple(sorted(differences)),
        })

    @staticmethod
    def _value(advice: AdviceCard, field: str):
        if field == "membership":
            return advice.quantitative_result.get("membership")
        if field == "simulation_plan":
            return (
                advice.simulation_plan_id,
                advice.quantitative_result.get("simulation_gate"),
            )
        return getattr(advice, field)

    @classmethod
    def removed(cls, previous: AdviceCard, reason: str, now: datetime) -> AdviceCard | None:
        if previous.action == "invalidated" and previous.conclusion == reason:
            return None
        identity = f"{previous.advice_id}|{reason}|{now.isoformat()}"
        proposed = previous.model_copy(update={
            "advice_id": f"advice-{hashlib.sha256(identity.encode()).hexdigest()[:24]}",
            "action": "invalidated", "conclusion": reason,
            "risks": tuple(dict.fromkeys((*previous.risks, reason))),
            "simulation_plan_id": None, "risk_decision_id": None,
            "created_at": now,
        })
        return cls.changed(previous, proposed)

    @staticmethod
    def validate_cutoff(advice: AdviceCard, cutoff: datetime, baseline: datetime | None = None) -> None:
        evidence = advice.supporting_evidence + advice.contrary_evidence
        if any(item.observed_at > cutoff for item in evidence):
            raise ValueError("future evidence is not allowed")
        if baseline is not None and any(item.observed_at < baseline for item in evidence):
            raise ValueError("evidence predates the advice baseline")


class PollState(BaseModel):
    model_config = ConfigDict(frozen=True)

    last_focus_success_at: AwareDatetime | None = None
    last_universe_success_at: AwareDatetime | None = None
    consecutive_focus_failures: int = 0
    consecutive_universe_failures: int = 0
    focus_interval_seconds: int = 60
    universe_interval_seconds: int = 180
    next_focus_due_at: AwareDatetime
    next_universe_due_at: AwareDatetime
    mode: Literal["normal", "degraded"] = "normal"
    last_error_code: str | None = None


class IntradayCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    result_id: str
    checked_at: AwareDatetime
    polled: frozenset[Scope]
    state: PollState


class PollStateRepository:
    def __init__(self, database: str | Path) -> None:
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS intraday_poll_state_events (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          occurred_at TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS intraday_market_snapshot_events (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          scope TEXT NOT NULL, symbol TEXT NOT NULL, observed_at TEXT NOT NULL,
          source_snapshot_id TEXT
        );
        CREATE TRIGGER IF NOT EXISTS reject_update_intraday_poll_state
        BEFORE UPDATE ON intraday_poll_state_events
        BEGIN SELECT RAISE(ABORT, 'append-only intraday poll state'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_intraday_poll_state
        BEFORE DELETE ON intraday_poll_state_events
        BEGIN SELECT RAISE(ABORT, 'append-only intraday poll state'); END;
        CREATE TRIGGER IF NOT EXISTS reject_update_intraday_market_snapshot
        BEFORE UPDATE ON intraday_market_snapshot_events
        BEGIN SELECT RAISE(ABORT, 'append-only intraday market snapshots'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_intraday_market_snapshot
        BEFORE DELETE ON intraday_market_snapshot_events
        BEGIN SELECT RAISE(ABORT, 'append-only intraday market snapshots'); END;
        """)

    def latest(self) -> PollState | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT payload FROM intraday_poll_state_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        return PollState.model_validate_json(row["payload"]) if row else None

    def append(self, state: PollState, occurred_at: datetime) -> None:
        payload = json.dumps(state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO intraday_poll_state_events(occurred_at,payload) VALUES(?,?)",
                (occurred_at.isoformat(), payload),
            )

    def append_snapshots(self, scope: Scope, snapshots) -> None:
        rows = [(
            scope, item.symbol, item.observed_at.isoformat(),
            getattr(item, "source_snapshot_id", None),
        ) for item in snapshots]
        with self._lock, self.connection:
            self.connection.executemany(
                """INSERT INTO intraday_market_snapshot_events(
                scope,symbol,observed_at,source_snapshot_id) VALUES(?,?,?,?)""",
                rows,
            )

    def snapshots(self) -> list[dict]:
        with self._lock:
            rows = self.connection.execute(
                """SELECT scope,symbol,observed_at,source_snapshot_id
                FROM intraday_market_snapshot_events ORDER BY sequence"""
            ).fetchall()
        return [dict(row) for row in rows]


class IntradayMonitor:
    def __init__(self, *, feed, calendar, state_repository: PollStateRepository,
                 focus_symbols, universe_symbols) -> None:
        self.feed = feed
        self.calendar = calendar
        self.state_repository = state_repository
        self.focus_symbols = focus_symbols
        self.universe_symbols = universe_symbols

    @property
    def state(self) -> PollState:
        stored = self.state_repository.latest()
        if stored is None:
            raise RuntimeError("poll state is not initialized")
        return stored

    def _state_at(self, now: datetime) -> PollState:
        stored = self.state_repository.latest()
        if stored is not None:
            return stored
        state = PollState(next_focus_due_at=now, next_universe_due_at=now)
        self.state_repository.append(state, now)
        return state

    def _in_window(self, now: datetime) -> bool:
        local = now.astimezone(CHINA_TZ)
        return self.calendar.is_trading_day(local.date()) and time(9, 25) <= local.time() <= time(15, 0)

    def due(self, now: datetime) -> frozenset[Scope]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if not self._in_window(now):
            return frozenset()
        state = self._state_at(now)
        return frozenset(
            scope for scope, due_at in (
                ("focus", state.next_focus_due_at), ("universe", state.next_universe_due_at)
            ) if now >= due_at
        )

    def check(self, now: datetime, *, scopes: frozenset[Scope] | None = None) -> IntradayCheckResult:
        selected = self.due(now) if scopes is None else scopes & self.due(now)
        state = self._state_at(now)
        polled: set[Scope] = set()
        for scope in ("focus", "universe"):
            if scope not in selected:
                continue
            raw = self.focus_symbols(now) if scope == "focus" else self.universe_symbols(now)
            symbols = tuple(dict.fromkeys(self._a_share_symbols(raw)))
            try:
                snapshots = self.feed.snapshot_many(symbols, cutoff=now)
                self.state_repository.append_snapshots(scope, snapshots)
            except Exception as error:
                state = self._failure(state, scope, now, error)
            else:
                state = self._success(state, scope, now)
                polled.add(scope)
            self.state_repository.append(state, now)
        return IntradayCheckResult(
            result_id=f"intraday-{int(now.timestamp())}", checked_at=now,
            polled=frozenset(polled), state=state,
        )

    @staticmethod
    def _a_share_symbols(values) -> tuple[str, ...]:
        accepted = []
        for value in values:
            symbol = getattr(value, "symbol", value)
            try:
                accepted.append(validate_a_share_code(symbol))
            except ValueError:
                continue
        return tuple(accepted)

    @staticmethod
    def _failure(state: PollState, scope: Scope, now: datetime, error: Exception) -> PollState:
        count_field = f"consecutive_{scope}_failures"
        interval_field = f"{scope}_interval_seconds"
        due_field = f"next_{scope}_due_at"
        count = getattr(state, count_field) + 1
        interval = BACKOFF[min(count - 1, len(BACKOFF) - 1)]
        code = re.sub(r"(?<!^)(?=[A-Z])", "_", error.__class__.__name__).lower()
        return state.model_copy(update={
            count_field: count, interval_field: interval,
            due_field: now + timedelta(seconds=interval),
            "mode": "degraded", "last_error_code": code,
        })

    @staticmethod
    def _success(state: PollState, scope: Scope, now: datetime) -> PollState:
        interval = 60 if scope == "focus" else 180
        other = "universe" if scope == "focus" else "focus"
        other_failures = getattr(state, f"consecutive_{other}_failures")
        return state.model_copy(update={
            f"last_{scope}_success_at": now,
            f"consecutive_{scope}_failures": 0,
            f"{scope}_interval_seconds": interval,
            f"next_{scope}_due_at": now + timedelta(seconds=interval),
            "mode": "degraded" if other_failures else "normal",
            "last_error_code": state.last_error_code if other_failures else None,
        })
