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
- A market-feed cadence port deterministically selects 180 or 300 seconds from source budget. Streaming is reserved capability negotiation only; no stream consumption is implemented.
- Simulation-plan identity hashes complete immutable levels, references, and level-derived validity timestamps; builder invocation time does not alter the plan body or ID.

## Re-review Fix Evidence

- RED: two due executions returning the same source snapshot left the restarted universe due time at the first execution.
- RED: changed quote/source content with identical evaluator semantics appended an empty second decision cycle.
- RED: identical plan levels/gates under source churn appended a second plan cycle because aggregate-local IDs were compared as semantics.
- RED: all blocked or missing gate variants retained stale simulated-plan references and failed Task 1 repository integrity validation.
- RED: a universe poll followed by focus-only polling lost the retained non-focus quote after restart.
- GREEN: monitor regression suite -> `25 passed in 2.30s` before final focused/full verification.
- FINAL GREEN: focused Task 3 suite -> `53 passed in 2.98s`.
- FINAL FULL: API suite -> `460 passed in 27.48s`.
- FINAL QUALITY: Ruff passed, mojibake scan returned no matches, and `git diff --check` exited 0.

## Re-review Design Decisions

- Poll execution identity is `scope + executed_at`; snapshot content identity is independent. Every distinct due execution atomically advances state even when the provider repeats content.
- Full frozen `MarketFeedSnapshot` payloads are append-persisted. Reconstruction selects the latest valid per-symbol payload from the current trading-day window, so current focus updates overlay retained universe quotes across restart.
- Aggregate append is gated exclusively by specified advice/removal/membership/gate/plan semantic deltas. Source hash changes without a semantic delta return the existing latest aggregate.
- Plan comparison excludes aggregate-local plan/advice IDs. Unchanged semantics preserve prior references when no advice delta exists; changed advice receives a newly reciprocal plan in its new aggregate.
- Any failed or absent plan gate normalizes stale plan advice to a non-plan action, clears plan/risk references, and records stable failed-gate reasons.

## Final Poll Persistence Review

- RED: the identical-content execution regression failed because no `success_states` audit existed and content rows were appended on every execution.
- RED: an older focus quote appended after a fresher universe quote, producing two rows and allowing sequence order to select stale content.
- GREEN: the two persistence/freshness regressions -> `2 passed in 0.82s`.
- FINAL GREEN: focused Task 3 suite -> `55 passed in 3.22s`.
- FINAL FULL: API suite -> `462 passed in 29.06s`.
- FINAL QUALITY: Ruff passed, mojibake scan returned no matches, and `git diff --check` exited 0.

The append transaction now treats execution and content as separate identities. A unique execution always appends its success state, while canonical quote content excludes observation/fetch/source identity metadata and inserts only when the latest content for that scope/symbol differs. Freshness is enforced globally per symbol before the per-scope content comparison: an incoming `(observed_at, fetched_at)` older than the freshest retained payload is ignored, including focus/universe crossover and restart cases.

## Trading-date Content Scope

- RED: identical valid content on the next Beijing trading day was suppressed by the prior day's per-scope hash (`expected 2 content rows, got 1`).
- GREEN: all monitor tests -> `28 passed in 2.21s` before final verification.
- FINAL GREEN: focused Task 3 suite -> `56 passed in 3.00s`.
- FINAL FULL: API suite -> `463 passed in 24.36s`.
- FINAL QUALITY: Ruff passed, mojibake scan returned no matches, and `git diff --check` exited 0.

Per-scope content deduplication and the global per-symbol freshness baseline are now restricted to the incoming snapshot's Beijing trading date. This preserves same-day duplicate suppression and stale crossover rejection while ensuring the first valid poll of each new confirmed trading day persists current-day content. A transient unrelated DuckDB path decode failure appeared once in the full suite; its route parameterization then passed `4 passed in 3.03s`, and the fresh full rerun passed completely.
