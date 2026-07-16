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

- The freshness cache is process-local. It is concurrency-safe within one API process, but separate worker processes do not share refresh state.
- Preparation deliberately reuses the diagnosis service's source-check adapters. If those adapters become public ports later, this service should switch to the public interface.
