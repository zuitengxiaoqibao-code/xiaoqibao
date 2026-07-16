# Beginner Task 2 Report

## Scope

- Added typed A-share preparation results and an asynchronous preparation service.
- Added `POST /api/v1/a-shares/{symbol}/prepare` with verified-symbol 404 handling.
- Added preparation state to cockpit snapshots.
- Removed the hard-coded `funds` and `backtest` cockpit sections.
- Wired the service to the existing history, diagnosis, and normalized-news services.

## RED Evidence

- `pytest apps/api/tests/a_shares/test_preparation.py -q` failed during collection with `ModuleNotFoundError: qibao_api.a_shares.preparation`.
- `pytest apps/api/tests/routes/test_research.py -q` failed during collection because `get_a_share_preparation_service` did not exist.
- The normalized-news scoping test failed because an unrelated or pending event supplied the news observation timestamp.
- The unexpected history failure test failed with an uncaught `TimeoutError`.

## GREEN Evidence

- Preparation tests cover missing-history refresh, post-refresh reassessment, repeat idempotency, concurrent coalescing, historical cutoff reads, typed source failures, normalized-news scoping, and unexpected sync exceptions.
- Route tests cover typed success and verified-symbol 404 behavior.
- Cockpit tests verify removed sections stay absent and the existing deterministic snapshot behavior remains intact.

## Files

- `apps/api/src/qibao_api/a_shares/preparation.py`
- `apps/api/src/qibao_api/a_shares/cockpit.py`
- `apps/api/src/qibao_api/dependencies.py`
- `apps/api/src/qibao_api/routes/research.py`
- `apps/api/src/qibao_api/main.py`
- `apps/api/tests/a_shares/test_preparation.py`
- `apps/api/tests/a_shares/test_cockpit.py`
- `apps/api/tests/routes/test_research.py`

## Self-review

- Only requests without a historical cutoff may call history sync or news ingestion.
- Historical reads pass their cutoff to bars and diagnosis source checks.
- Source failures become `partial` preparation sources; no evidence is fabricated.
- Per-symbol/date/cutoff locks coalesce concurrent refreshes, and the cached history version makes a repeat refresh observable as `refreshed=false`.
- News evidence is limited to verified normalized events linked to the requested A-share.
- Task 1 removals were preserved; no paper-trading or simulation behavior was added.

## Concerns

- File locks coordinate workers sharing the configured data directory; deployments that place workers on separate hosts need a shared/distributed lock provider.

## Review Remediation

### Additional RED Evidence

- The review regression suite initially failed all five tests because shared lock paths and read-only inspection did not exist.
- The cockpit read-only test failed because the preparation dependency occupied the assessor slot and cockpit still used the mutation path.
- The cross-instance Windows lock test failed with `PermissionError` while reading a byte already locked by another handle.
- The bounded news repository test returned no rows because stored UTC timestamps use `Z` while the SQL cutoff used `+00:00`.
- The full API suite found one legacy cockpit fixture without the now-required preparation inspector.

### Architecture Changes

- Cockpit GET now requires a preparation inspector and calls only `inspect`; the mutation fallback was removed.
- POST preparation remains under the runtime write middleware and has an explicit concurrent-request serialization test.
- History refresh uses per-symbol cross-process file locks. Global news ingestion uses one cross-process lock and a shared success-marker cooldown across symbols and service instances.
- File-lock acquisition and release run through `asyncio.to_thread`; no event-loop-blocking lock wait remains.
- In-memory lock/result dictionaries and the count/date result cache were removed. Every inspection recomputes quote, finance, history, and bounded news readiness; partial refreshes create no success cache and retry.
- History freshness uses the trading calendar, the previous confirmed session on weekends/holidays, and the previous session before the current trading day's close.
- Preparation uses the public `inspect_sources` diagnosis API and `events_for_symbol` repository query. The latter filters verified A-share links and cutoff timestamps in SQLite before model validation.
- A successful fresh global collection with no linked stock event is ready-empty; collection failure is partial.

### Added GREEN Coverage

- Read-only cockpit and repeated source inspection.
- Cross-instance history locking and lock-state eviction.
- Cross-instance, cross-symbol global news locking/cooldown.
- Failure retry without partial caching.
- Weekend and pre-close history freshness.
- Bounded symbol/cutoff news queries.
- Concurrent POST middleware serialization.

## Second Review Remediation

### RED Evidence

- The expanded preparation review suite failed because lock timeout configuration, cancellation-safe acquisition, async calendar inspection, and atomic marker publication did not exist.
- Cancellation previously abandoned a worker-thread acquisition that could later own the file lock without any release path.
- Windows used the built-in blocking lock mode, which has an unsuitable retry interval and no application deadline.

### Changes

- File locking now uses `LK_NBLCK` on Windows and `LOCK_NB` on POSIX with a monotonic deadline, short configurable retry interval, and typed `PreparationLockTimeout`.
- History and global-news lock timeouts degrade their source result to `partial` with a stable reason instead of escaping as HTTP 500 errors.
- Async lock acquisition is a retained task awaited through `asyncio.shield`. Cancellation attaches a completion callback that releases exactly once if background acquisition later succeeds.
- Normal context exit also shields the release thread, including cancellation during the protected operation.
- All trading-calendar work, including a potentially blocking live signal, runs through `asyncio.to_thread` for prepare and inspect.
- News success markers are written to a unique temporary file, flushed, synced, and atomically replaced. Readers therefore see the previous complete marker or the new complete marker.

### GREEN Coverage

- Cancellation during contention followed by successful third-party acquisition.
- Typed partial degradation on a short contention deadline.
- Multiple nonblocking retries followed by acquisition after the holder releases.
- Event-loop responsiveness with a deliberately blocking calendar.
- Atomic marker publication while inspecting the destination immediately before replacement.

## Controller Concurrency Regression

### RED And Root Cause

- A failed history/news refresh returned `refreshed=true` because the flag represented an attempted mutation rather than a successful evidence write.
- Independent history and global-news locks allowed two same-symbol workers to split the work: one could write history while the waiter wrote the news marker, causing both results to claim refresh ownership.

### Fix

- Live preparation now uses an outer cross-process per-symbol preparation lock around the complete history-plus-news unit. Waiters acquire it later and reassess history and the global news marker inside their respective locks.
- History refresh becomes true only after a ready sync report and either positive written rows or a changed bar payload version.
- News refresh becomes true only after collection succeeds and the atomic success marker is published.
- Any history/news mutation failure or lock timeout forces the partial result's `refreshed` field to false.

### Evidence

- Failure/retry coverage now asserts the failed call is not refreshed and the successful retry is refreshed.
- Lock-timeout coverage asserts partial plus `refreshed=false`.
- The two-instance shared-history/global-news concurrency test passed 20 consecutive isolated runs after the fix.
