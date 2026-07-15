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

- Production wiring must provide concrete implementations of the explicit candidate/factor, risk, compliance, evidence, and deterministic evaluation ports. The monitor now owns the complete aggregate lifecycle once those domain adapters are injected.

## Review Fix Evidence

- RED: imports failed for missing `DeterministicPollingCadence` and `IntradayEvaluationResult` before the reviewed boundary contracts were added.
- RED: real `DecisionRepository` integration initially rejected a malformed test baseline with `advice references a different snapshot`; the fixture was corrected without weakening repository validation.
- RED: unchanged canonical source content incorrectly hid a changed evaluator conclusion (`expected 2 cycles, got 1`); normalized advice and gate output are now part of the canonical hash.
- RED: background `tick_intraday` called the monitor on an unconfirmed trading day; scheduler-level calendar validation now prevents both the call and job event.
- GREEN: reviewed focused suite -> `40 passed in 2.70s` before the final scheduler regression was added.
- FULL: reviewed API suite -> `447 passed in 24.45s` before the final scheduler regression was added.
- FINAL GREEN: focused Task 3 suite -> `41 passed in 1.64s`.
- FINAL FULL: API suite -> `448 passed in 32.18s`.
- FINAL LINT/ENCODING/DIFF: Ruff passed, mojibake scan returned no matches, and `git diff --check` exited 0.

## Review Design Decisions

- `IntradayEvaluationPort` receives current reconstructed advice, validated quotes, exact Beijing-market window, and values from explicit candidate/factor, risk, compliance, and evidence ports.
- The monitor loads premarket plus all intraday deltas to reconstruct current advice, applies exact deterministic diffs and stable `candidate_removed` reason codes, builds reciprocal plans, and appends through Task 1's repository.
- Canonical hashing includes normalized quote values, evaluator source content, advice fields, and gate inputs while excluding ephemeral IDs and timestamps.
- Successful snapshot batches and their resulting state event share one SQLite transaction and stable batch identity; duplicate batches are no-ops across restart.
- A market-feed cadence port deterministically selects 180 or 300 seconds from source budget, and stream delivery is capability-negotiated without invoking polling.
- Simulation-plan identity hashes complete immutable levels, references, and level-derived validity timestamps; builder invocation time does not alter the plan body or ID.
