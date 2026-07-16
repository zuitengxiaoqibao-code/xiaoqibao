# Phase Lifecycle And Premarket Trading Day Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live A-share workflow identify the current trading day before the open and explain every premarket, intraday, and postclose phase as scheduled, running, completed, failed, or overdue.

**Architecture:** Combine the maintained XSHG exchange calendar with existing local-bar and Tencent live confirmation signals. Derive phase execution metadata from the scheduler's authoritative slot table, immutable decision snapshots, and append-only operations ledger, then expose the same metadata through both decision and single-stock responses.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, exchange-calendars, React 19, TypeScript, Vitest.

## Global Constraints

- A-shares remain the primary asset domain; convertible bonds stay isolated.
- Never infer a missing quote, recommendation, execution result, or exchange holiday.
- Do not add simulated accounts, funds, orders, trades, or broker execution.
- Chinese source files must be edited with `apply_patch`, scanned for mojibake, and verified by build/tests.

---

### Task 1: Confirm Premarket Trading Dates

**Files:**
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/uv.lock`
- Modify: `apps/api/src/qibao_api/shangshu/trading_calendar.py`
- Modify: `apps/api/src/qibao_api/main.py`
- Test: `apps/api/tests/shangshu/test_trading_calendar.py`

**Interfaces:**
- Produces: `ExchangeCalendarsTradingDaySchedule.is_trading_day(value: date) -> bool`
- Consumes: the existing `StoredTradingCalendar`, local bar dates, and Tencent live date signal.

- [x] **Step 1: Write the failing exchange-calendar tests**

```python
schedule = ExchangeCalendarsTradingDaySchedule()
assert schedule.is_trading_day(date(2026, 7, 17)) is True
assert schedule.is_trading_day(date(2026, 10, 1)) is False
```

- [x] **Step 2: Run the focused test and verify it fails because the schedule adapter is absent**

Run: `uv run --project apps/api pytest apps/api/tests/shangshu/test_trading_calendar.py -q`

- [x] **Step 3: Add the pinned dependency and minimal adapter**

```python
class ExchangeCalendarsTradingDaySchedule:
    def is_trading_day(self, value: date) -> bool:
        return bool(self.calendar.is_session(pd.Timestamp(value)))
```

- [x] **Step 4: Compose the official schedule with existing evidence and rerun the focused tests**

### Task 2: Expose Authoritative Phase Execution State

**Files:**
- Create: `apps/api/src/qibao_api/shangshu/phase_lifecycle.py`
- Modify: `apps/api/src/qibao_api/routes/decisions.py`
- Modify: `apps/api/src/qibao_api/a_shares/cockpit.py`
- Modify: `apps/api/src/qibao_api/main.py`
- Test: `apps/api/tests/routes/test_decisions.py`
- Test: `apps/api/tests/a_shares/test_cockpit.py`

**Interfaces:**
- Produces: `PhaseExecution` with `status`, `scheduled_at`, `next_scheduled_at`, `last_completed_at`, `last_attempt_at`, `attempts`, and `error_code`.
- Consumes: scheduler `SCHEDULE`, decision aggregates, and `OperationsRepository.jobs()`.

- [x] **Step 1: Write failing tests for scheduled, running, completed, failed, and overdue states**

```python
assert body["phases"]["premarket"]["execution"]["status"] == "scheduled"
assert body["phases"]["premarket"]["execution"]["scheduled_at"].endswith("09:20:00+08:00")
```

- [x] **Step 2: Run route and cockpit tests and verify the execution field is missing**

- [x] **Step 3: Implement one pure lifecycle resolver and reuse it in both APIs**

```python
def resolve_phase_execution(*, phase, trading_date, now, aggregate, jobs):
    ...
```

- [x] **Step 4: Rerun focused API tests and keep phase data quality separate from job execution status**

### Task 3: Render Beginner-Friendly Phase Messages

**Files:**
- Modify: `apps/web/src/features/decision-workbench/types.ts`
- Modify: `apps/web/src/features/decision-workbench/DecisionWorkbench.tsx`
- Modify: `apps/web/src/features/stock-cockpit/types.ts`
- Modify: `apps/web/src/features/stock-cockpit/PhaseTimeline.tsx`
- Modify: `apps/web/src/features/beginner-shell/HistoryReview.tsx`
- Test: corresponding `*.test.tsx` files.

**Interfaces:**
- Consumes: the backend `PhaseExecution` contract without deriving schedule status from the browser clock.

- [x] **Step 1: Write failing UI tests for `计划 09:20 生成`, running, failed, and overdue copy**

- [x] **Step 2: Run the focused Vitest files and verify the old generic empty message fails**

- [x] **Step 3: Add a shared beginner message formatter and render truthful lifecycle copy**

```typescript
phaseExecutionMessage(slot.execution, Boolean(slot.aggregate_version));
```

- [x] **Step 4: Rerun focused tests and verify existing completed/excluded-stock wording remains intact**

### Task 4: Runtime And Regression Acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`

- [x] **Step 1: Restart the API and verify `/api/v1/decisions/current` returns today's confirmed trading date before 09:20**
- [x] **Step 2: Verify `000001` and `600519` cockpit responses use the same lifecycle contract**
- [x] **Step 3: Inspect desktop and mobile pages for readable lifecycle copy and no overflow**
- [x] **Step 4: Run full API tests, Ruff, web tests, production build, mojibake scan, and `git diff --check`**
- [ ] **Step 5: Commit the verified change and push normally when GitHub connectivity is available**
