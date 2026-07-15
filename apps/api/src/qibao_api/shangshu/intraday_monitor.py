import json
import hashlib
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

from qibao_api.contracts.instruments import validate_a_share_code
from qibao_api.bingbu.simulation_plan import SimulationGateContext, SimulationPlanBuilder
from qibao_api.contracts.decision import (
    AdviceCard, DecisionCycleAggregate, DecisionCycleSnapshot, SimulationPlan,
)
from qibao_api.gongbu.market_feed import DeterministicPollingCadence, MarketFeedSnapshot


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
        if (previous.action == "invalidated"
                and previous.quantitative_result.get("invalidation_reason_code") == reason):
            return None
        identity = f"{previous.advice_id}|{reason}|{now.isoformat()}"
        proposed = previous.model_copy(update={
            "advice_id": f"advice-{hashlib.sha256(identity.encode()).hexdigest()[:24]}",
            "action": "invalidated", "conclusion": reason,
            "risks": tuple(dict.fromkeys((*previous.risks, reason))),
            "quantitative_result": {
                **previous.quantitative_result, "invalidation_reason_code": reason,
            },
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
    aggregate: DecisionCycleAggregate | None = None


class IntradayEvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    advice: tuple[AdviceCard, ...]
    gates: dict[str, SimulationGateContext]
    source_content: dict[str, Any]
    market_state: Literal["strong", "range", "weak", "insufficient_data"]
    data_quality: Literal["ready", "partial", "blocked"]
    status: Literal["ready", "partial", "blocked"]
    candidate_snapshot_id: str | None
    news_event_ids: tuple[str, ...]
    risk_event_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntradayEvaluationContext:
    now: datetime
    window_start: datetime
    window_end: datetime
    quotes: tuple[MarketFeedSnapshot, ...]
    current_advice: tuple[AdviceCard, ...]
    candidate_factor_input: Any
    risk_input: Any
    compliance_input: Any
    evidence_input: Any


class IntradayEvaluationPort(Protocol):
    def evaluate(self, context: IntradayEvaluationContext) -> IntradayEvaluationResult: ...


class IntradayInputPort(Protocol):
    def snapshot(self, *, now: datetime, cutoff: datetime) -> Any: ...


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
          source_snapshot_id TEXT, payload TEXT, content_hash TEXT
        );
        CREATE TABLE IF NOT EXISTS intraday_poll_batches (
          batch_id TEXT PRIMARY KEY, scope TEXT NOT NULL, occurred_at TEXT NOT NULL
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
        columns = {
            row["name"] for row in self.connection.execute(
                "PRAGMA table_info(intraday_market_snapshot_events)"
            ).fetchall()
        }
        if "payload" not in columns:
            self.connection.execute(
                "ALTER TABLE intraday_market_snapshot_events ADD COLUMN payload TEXT"
            )
        if "content_hash" not in columns:
            self.connection.execute(
                "ALTER TABLE intraday_market_snapshot_events ADD COLUMN content_hash TEXT"
            )

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
            getattr(item, "source_snapshot_id", None), self._snapshot_payload(item),
        ) for item in snapshots]
        with self._lock, self.connection:
            self.connection.executemany(
                """INSERT INTO intraday_market_snapshot_events(
                scope,symbol,observed_at,source_snapshot_id,payload) VALUES(?,?,?,?,?)""",
                rows,
            )

    def append_success_batch(
        self, batch_id: str, scope: Scope, snapshots, state: PollState,
        occurred_at: datetime,
    ) -> bool:
        payload = json.dumps(state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        with self._lock, self.connection:
            existing = self.connection.execute(
                "SELECT 1 FROM intraday_poll_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if existing is not None:
                return False
            self.connection.execute(
                "INSERT INTO intraday_poll_batches(batch_id,scope,occurred_at) VALUES(?,?,?)",
                (batch_id, scope, occurred_at.isoformat()),
            )
            for item in snapshots:
                snapshot_payload = self._snapshot_payload(item)
                content_hash = self._snapshot_content_hash(item)
                if self._is_stale_snapshot(item):
                    continue
                prior = self.connection.execute(
                    """SELECT content_hash,payload FROM intraday_market_snapshot_events
                    WHERE scope=? AND symbol=? ORDER BY sequence DESC LIMIT 1""",
                    (scope, item.symbol),
                ).fetchone()
                prior_hash = None if prior is None else prior["content_hash"]
                if prior_hash is None and prior is not None and prior["payload"]:
                    prior_hash = self._snapshot_content_hash(
                        MarketFeedSnapshot.model_validate_json(prior["payload"])
                    )
                if prior_hash == content_hash:
                    continue
                self.connection.execute(
                    """INSERT INTO intraday_market_snapshot_events(
                    scope,symbol,observed_at,source_snapshot_id,payload,content_hash)
                    VALUES(?,?,?,?,?,?)""",
                    (scope, item.symbol, item.observed_at.isoformat(),
                     getattr(item, "source_snapshot_id", None), snapshot_payload,
                     content_hash),
                )
            self.connection.execute(
                "INSERT INTO intraday_poll_state_events(occurred_at,payload) VALUES(?,?)",
                (occurred_at.isoformat(), payload),
            )
        return True

    @staticmethod
    def _snapshot_payload(snapshot) -> str | None:
        if not isinstance(snapshot, MarketFeedSnapshot):
            return None
        return json.dumps(
            snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    def _snapshot_content_hash(snapshot) -> str:
        if isinstance(snapshot, MarketFeedSnapshot):
            value = snapshot.model_dump(mode="json")
            for field in ("observed_at", "fetched_at", "source_snapshot_id"):
                value.pop(field, None)
        else:
            value = {"symbol": snapshot.symbol}
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def _is_stale_snapshot(self, snapshot) -> bool:
        rows = self.connection.execute(
            """SELECT payload FROM intraday_market_snapshot_events
            WHERE symbol=? AND payload IS NOT NULL""",
            (snapshot.symbol,),
        ).fetchall()
        if not rows or not isinstance(snapshot, MarketFeedSnapshot):
            return False
        retained = [MarketFeedSnapshot.model_validate_json(row["payload"]) for row in rows]
        freshest = max((item.observed_at, item.fetched_at) for item in retained)
        return (snapshot.observed_at, snapshot.fetched_at) < freshest

    def latest_snapshots(
        self, cutoff: datetime, *, since: datetime | None = None,
    ) -> tuple[MarketFeedSnapshot, ...]:
        with self._lock:
            rows = self.connection.execute(
                """SELECT symbol,payload FROM intraday_market_snapshot_events
                WHERE payload IS NOT NULL ORDER BY sequence""",
            ).fetchall()
        latest = {}
        for row in rows:
            snapshot = MarketFeedSnapshot.model_validate_json(row["payload"])
            if snapshot.observed_at > cutoff:
                continue
            if since is not None and snapshot.observed_at < since:
                continue
            latest[row["symbol"]] = snapshot
        return tuple(latest[symbol] for symbol in sorted(latest))

    def snapshots(self) -> list[dict]:
        with self._lock:
            rows = self.connection.execute(
                """SELECT scope,symbol,observed_at,source_snapshot_id
                FROM intraday_market_snapshot_events ORDER BY sequence"""
            ).fetchall()
        return [dict(row) for row in rows]

    def success_states(self, scope: Scope) -> list[PollState]:
        field = f"last_{scope}_success_at"
        with self._lock:
            rows = self.connection.execute(
                "SELECT payload FROM intraday_poll_state_events ORDER BY sequence"
            ).fetchall()
        results = []
        previous = None
        for row in rows:
            state = PollState.model_validate_json(row["payload"])
            value = getattr(state, field)
            if value is not None and value != previous:
                results.append(state)
            previous = value
        return results


class IntradayMonitor:
    def __init__(self, *, feed, calendar, state_repository: PollStateRepository,
                 focus_symbols, universe_symbols, decision_repository=None,
                 evaluator: IntradayEvaluationPort | None = None,
                 cadence=None, source_budget=None,
                 candidate_factor_port: IntradayInputPort | None = None,
                 risk_port: IntradayInputPort | None = None,
                 compliance_port: IntradayInputPort | None = None,
                 evidence_port: IntradayInputPort | None = None,
                 delivery_mode: Literal["poll", "stream"] = "poll") -> None:
        self.feed = feed
        self.calendar = calendar
        self.state_repository = state_repository
        self.focus_symbols = focus_symbols
        self.universe_symbols = universe_symbols
        self.decision_repository = decision_repository
        self.evaluator = evaluator
        self.cadence = cadence or DeterministicPollingCadence()
        self.source_budget = source_budget or (lambda _now: "available")
        self.delivery_mode = delivery_mode
        self.input_ports = (
            candidate_factor_port, risk_port, compliance_port, evidence_port,
        )
        if delivery_mode == "stream" and "subscribe" not in getattr(feed, "capabilities", ()):
            raise ValueError("selected market feed does not support streaming")
        if (decision_repository is None) != (evaluator is None):
            raise ValueError("decision repository and evaluator must be configured together")
        if evaluator is not None and any(port is None for port in self.input_ports):
            raise ValueError("all deterministic intraday input ports are required")

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
        if self.delivery_mode == "stream":
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
            except Exception as error:
                state = self._failure(state, scope, now, error)
                self.state_repository.append(state, now)
            else:
                interval = 60 if scope == "focus" else self.cadence.universe_interval_seconds(
                    source_budget=self.source_budget(now)
                )
                state = self._success(state, scope, now, interval)
                batch_id = self._batch_id(scope, now)
                self.state_repository.append_success_batch(
                    batch_id, scope, snapshots, state, now,
                )
                polled.add(scope)
        local = now.astimezone(CHINA_TZ)
        window_start = datetime.combine(local.date(), time(9, 25), CHINA_TZ)
        layered_quotes = self.state_repository.latest_snapshots(now, since=window_start)
        aggregate = self._evaluate(now, layered_quotes)
        return IntradayCheckResult(
            result_id=f"intraday-{int(now.timestamp())}", checked_at=now,
            polled=frozenset(polled), state=state, aggregate=aggregate,
        )

    @staticmethod
    def _batch_id(scope: Scope, executed_at: datetime) -> str:
        payload = json.dumps(
            {"scope": scope, "executed_at": executed_at.isoformat()},
            sort_keys=True, separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

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
    def _success(state: PollState, scope: Scope, now: datetime, interval: int) -> PollState:
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

    def _evaluate(
        self, now: datetime, quotes: tuple[MarketFeedSnapshot, ...],
    ) -> DecisionCycleAggregate | None:
        if self.evaluator is None or not quotes:
            return None
        local = now.astimezone(CHINA_TZ)
        trading_date = local.date()
        window_start = datetime.combine(trading_date, time(9, 25), CHINA_TZ)
        window_end = min(now, datetime.combine(trading_date, time(15, 0), CHINA_TZ))
        current = self._current_advice(trading_date)
        current_plans = self._current_plans(trading_date)
        inputs = tuple(
            port.snapshot(now=now, cutoff=window_end) for port in self.input_ports
            if port is not None
        )
        for value in inputs:
            self._validate_input_cutoff(value, window_end)
        result = self.evaluator.evaluate(IntradayEvaluationContext(
            now=now, window_start=window_start, window_end=window_end,
            quotes=quotes, current_advice=tuple(current.values()),
            candidate_factor_input=inputs[0], risk_input=inputs[1],
            compliance_input=inputs[2], evidence_input=inputs[3],
        ))
        if any(item.asset.value != "a_share" for item in result.advice):
            raise ValueError("intraday evaluator returned a non-A-share advice")
        for item in result.advice:
            AdviceChangeDetector.validate_cutoff(item, window_end, window_start)
        source_hash = self._source_hash(result, quotes)
        latest = self.decision_repository.latest(trading_date, "intraday")
        if latest is not None and latest.snapshot.input_snapshot_hash == source_hash:
            return latest
        sequence = 1 if latest is None else latest.snapshot.sequence + 1
        previous_snapshot_id = None if latest is None else latest.snapshot.snapshot_id
        snapshot_id = f"intraday-{trading_date.isoformat()}-{sequence}-{source_hash[:16]}"
        proposed_keys = {(item.symbol, item.horizon) for item in result.advice}
        changed = []
        plans = []
        for item in result.advice:
            key = (item.symbol, item.horizon)
            previous = current.get(key)
            advice_id = f"advice-{hashlib.sha256(f'{snapshot_id}|{item.symbol}|{item.horizon}'.encode()).hexdigest()[:24]}"
            candidate = item.model_copy(update={
                "advice_id": advice_id, "snapshot_id": snapshot_id,
                "created_at": now, "previous_advice_id": None, "changed_fields": (),
            })
            gate = result.gates.get(item.advice_id)
            plan = None
            plan_semantics_unchanged = False
            if gate is not None:
                semantic_advice_id = previous.advice_id if previous is not None else advice_id
                semantic_gate = gate.model_copy(update={"advice_id": semantic_advice_id})
                semantic_plan = SimulationPlanBuilder(now=now).build(semantic_gate)
                previous_plan = (
                    current_plans.get(previous.simulation_plan_id)
                    if previous is not None and previous.simulation_plan_id else None
                )
                plan_semantics_unchanged = self._same_plan_semantics(
                    semantic_plan, previous_plan,
                )
                if semantic_plan is not None and plan_semantics_unchanged and previous is not None:
                    candidate = candidate.model_copy(update={
                        "action": "simulated_plan",
                        "simulation_plan_id": previous.simulation_plan_id,
                        "risk_decision_id": previous.risk_decision_id,
                    })
                elif semantic_plan is not None:
                    bound_gate = gate.model_copy(update={"advice_id": advice_id})
                    plan = SimulationPlanBuilder(now=now).build(bound_gate)
                    candidate = candidate.model_copy(update={
                        "action": "simulated_plan", "simulation_plan_id": plan.plan_id,
                        "risk_decision_id": plan.risk_decision_id,
                    })
                else:
                    reasons = semantic_gate.failed_gate_reasons()
                    allowed = {"observe", "wait", "avoid", "invalidated"}
                    fallback = item.action if item.action in allowed else (
                        previous.action if previous is not None and previous.action in allowed
                        else "observe"
                    )
                    candidate = candidate.model_copy(update={
                        "action": fallback, "simulation_plan_id": None,
                        "risk_decision_id": None,
                        "risks": tuple(dict.fromkeys((*candidate.risks, *reasons))),
                    })
            elif candidate.action == "simulated_plan":
                allowed = {"observe", "wait", "avoid", "invalidated"}
                fallback = (
                    previous.action if previous is not None and previous.action in allowed
                    else "observe"
                )
                candidate = candidate.model_copy(update={
                    "action": fallback, "simulation_plan_id": None,
                    "risk_decision_id": None,
                    "risks": tuple(dict.fromkeys((
                        *candidate.risks, "simulation_gate_missing",
                    ))),
                })
            updated = candidate if previous is None else AdviceChangeDetector.changed(previous, candidate)
            if updated is not None:
                if gate is not None and plan_semantics_unchanged and candidate.action == "simulated_plan":
                    rebound_gate = gate.model_copy(update={"advice_id": updated.advice_id})
                    plan = SimulationPlanBuilder(now=now).build(rebound_gate)
                    assert plan is not None
                    updated = updated.model_copy(update={
                        "simulation_plan_id": plan.plan_id,
                        "risk_decision_id": plan.risk_decision_id,
                    })
                changed.append(updated)
                if plan is not None:
                    plans.append(plan)
        for key, previous in current.items():
            if key not in proposed_keys:
                invalidated = AdviceChangeDetector.removed(previous, "candidate_removed", now)
                if invalidated is not None:
                    changed.append(invalidated.model_copy(update={"snapshot_id": snapshot_id}))
        if not changed:
            return latest or self.decision_repository.latest(trading_date, "premarket")
        snapshot = DecisionCycleSnapshot(
            snapshot_id=snapshot_id, trading_date=trading_date, phase="intraday",
            sequence=sequence, generated_at=now, window_start=window_start,
            window_end=window_end, market_state=result.market_state,
            data_quality=result.data_quality,
            source_snapshot_ids=tuple(sorted({item.source_snapshot_id for item in quotes})),
            source_observed_at=tuple(sorted({item.observed_at for item in quotes})),
            candidate_snapshot_id=result.candidate_snapshot_id,
            news_event_ids=tuple(sorted(result.news_event_ids)),
            risk_event_ids=tuple(sorted(result.risk_event_ids)),
            input_snapshot_hash=source_hash, previous_snapshot_id=previous_snapshot_id,
            status=result.status, ai_status="not_requested",
        )
        aggregate = DecisionCycleAggregate(
            snapshot=snapshot,
            advice=tuple(sorted(changed, key=lambda item: item.advice_id)),
            plans=tuple(sorted(plans, key=lambda item: item.plan_id)),
        )
        self.decision_repository.append_cycle(aggregate)
        return aggregate

    def _current_advice(self, trading_date) -> dict[tuple[str, str], AdviceCard]:
        values: dict[tuple[str, str], AdviceCard] = {}
        premarket = self.decision_repository.latest(trading_date, "premarket")
        if premarket is not None:
            values.update({(item.symbol, item.horizon): item for item in premarket.advice})
        for cycle in self.decision_repository.cycles(trading_date, "intraday"):
            values.update({(item.symbol, item.horizon): item for item in cycle.advice})
        return values

    def _current_plans(self, trading_date) -> dict[str, SimulationPlan]:
        values: dict[str, SimulationPlan] = {}
        for phase in ("premarket", "intraday"):
            for cycle in self.decision_repository.cycles(trading_date, phase):
                values.update({item.plan_id: item for item in cycle.plans})
        return values

    @staticmethod
    def _same_plan_semantics(
        proposed: SimulationPlan | None, previous: SimulationPlan | None,
    ) -> bool:
        if proposed is None or previous is None:
            return proposed is previous
        ignored = {"plan_id", "advice_id"}
        proposed_value = proposed.model_dump(mode="json", exclude=ignored)
        previous_value = previous.model_dump(mode="json", exclude=ignored)
        return proposed_value == previous_value

    @staticmethod
    def _source_hash(result: IntradayEvaluationResult, quotes) -> str:
        quote_content = []
        for item in quotes:
            value = item.model_dump(mode="json")
            for field in ("observed_at", "fetched_at", "source_snapshot_id"):
                value.pop(field, None)
            quote_content.append(value)
        advice_content = []
        gate_content = []
        for item in sorted(result.advice, key=lambda value: (value.symbol, value.horizon)):
            value = item.model_dump(mode="json")
            for field in (
                "advice_id", "snapshot_id", "created_at", "previous_advice_id",
                "changed_fields",
            ):
                value.pop(field, None)
            advice_content.append(value)
            gate = result.gates.get(item.advice_id)
            if gate is not None:
                gate_value = gate.model_dump(mode="json")
                gate_value.pop("advice_id", None)
                gate_content.append({
                    "symbol": item.symbol, "horizon": item.horizon, "gate": gate_value,
                })
        payload = json.dumps({
            "source_content": result.source_content,
            "quotes": quote_content,
            "advice": advice_content,
            "gates": gate_content,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @classmethod
    def _validate_input_cutoff(cls, value: Any, cutoff: datetime) -> None:
        if isinstance(value, (tuple, list, set, frozenset)):
            for item in value:
                cls._validate_input_cutoff(item, cutoff)
            return
        observed_at = getattr(value, "observed_at", None)
        if observed_at is not None and observed_at > cutoff:
            raise ValueError("future deterministic input is not allowed")
