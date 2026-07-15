# Task 3 Report

## Status

Implemented the A-share polling feed port, append-only persisted layered polling state and market snapshots, deterministic advice change detection, simulation-plan gate, and separate scheduler monitor jobs. No postclose, HTTP API, or UI work was added.

## Commits

- `feat(decisions): monitor intraday advice changes` (this task commit)

## TDD Evidence

- RED: focused collection failed with three `ModuleNotFoundError` errors before the new modules existed.
- RED: stale quantitative levels initially raised `ValueError`; the test required and drove a Pydantic `ValidationError`.
- RED: importing `AdviceChangeDetector` failed before exact diff and one-time invalidation behavior was implemented.
- RED: snapshot persistence test failed with missing `PollStateRepository.snapshots` before append-only snapshot events were added.
- GREEN: `.venv\Scripts\python.exe -m pytest apps/api/tests/gongbu/test_market_feed.py apps/api/tests/shangshu/test_intraday_monitor.py apps/api/tests/bingbu/test_simulation_plan.py apps/api/tests/shangshu/test_scheduler.py -q` -> `30 passed in 1.19s`.
- FULL: `.venv\Scripts\python.exe -m pytest apps/api/tests -q` -> `437 passed in 31.62s`.
- LINT: focused `ruff check` -> `All checks passed!`.
- ENCODING: required mojibake scan returned no matches.
- DIFF: `git diff --check` exited 0.

## Files

- `apps/api/src/qibao_api/gongbu/market_feed.py`
- `apps/api/src/qibao_api/shangshu/intraday_monitor.py`
- `apps/api/src/qibao_api/bingbu/simulation_plan.py`
- `apps/api/src/qibao_api/shangshu/scheduler.py`
- `apps/api/tests/gongbu/test_market_feed.py`
- `apps/api/tests/shangshu/test_intraday_monitor.py`
- `apps/api/tests/bingbu/test_simulation_plan.py`
- `apps/api/tests/shangshu/test_scheduler.py`

## Decisions And Deviations

- Poll state and normalized snapshot batches use append-only SQLite event tables. State is recovered from the latest event after restart.
- Batch snapshots are appended only after the feed validates the complete requested symbol set and cutoff.
- Advice diffing is a deterministic reusable component. It compares only the specified decision fields and leaves aggregate construction/recomputation dependency-injected rather than coupling the monitor to Task 2 internals.
- Stale-level validation defaults to five minutes and raises a Pydantic validation error; no numeric fallback exists.
- Scheduled phase monitor jobs and high-frequency background ticks use distinct job keys and do not alter briefing or decision job status.

## Self-review

- Confirmed A-share validation rejects convertible bonds and filters candidate-universe contamination.
- Confirmed polling failures persist error codes, backoff intervals, degraded mode, and restart due times.
- Confirmed plan values are copied exactly and all four gates plus required references block independently.
- Confirmed scheduler monitor failures remain isolated from briefing and premarket decision jobs.

## Concerns

- The source-budget hook for increasing the normal universe interval from 180 toward 300 seconds is represented by the persisted interval field and the 300-second failure cap, but no provider budget interface exists in Tasks 1/2 to drive a non-failure increase.
- Full aggregate recomputation requires application-specific factor/risk/compliance/evidence adapters. This task supplies cutoff validation, exact diffing, invalidation, polling, and persistence without inventing those unavailable adapter contracts.
