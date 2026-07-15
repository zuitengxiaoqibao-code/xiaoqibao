# Task 2 Implementation Report

## Status

Implemented the read-only single-stock cockpit aggregate and API. Task 3 was not touched.

## Delivered behavior

- Added frozen `CockpitSection`, `StockPhaseHistory`, `DecisionVersion`, and
  `StockCockpitSnapshot` response contracts.
- Added `StockDecisionCockpitService.get()` as an async method to match the existing
  async `AShareDiagnosisService.diagnose()` lifecycle.
- Resolves one known A-share instrument and returns an explicit 404 for an unknown code.
- Reads each decision phase at the requested trading date and applies one server cutoff.
- Filters every advice record to the selected symbol and rejects records created after the
  cutoff or containing evidence observed after the cutoff.
- Preserves the selected stock's immutable phase version sequence in `change_stream`.
- Derives current advice by latest `(horizon, created_at)` record.
- Derives candidate membership from already persisted decision advice, avoiding a call to
  `candidates()` that could generate and persist a new candidate board.
- Maps diagnosis `events` to the public cockpit `news` section.
- Converts each diagnosis section independently, including cutoff rejection for a section
  observed after the requested cutoff.
- Always returns `funds` as unavailable with `fund_data_not_connected`.
- Always returns `backtest` as unavailable with `backtest_not_run`; no backtest strategy is
  selected or executed.
- Leaves `DecisionIntegrityError` unhandled in the service and maps it at the HTTP boundary
  to a generic 503 `decision_integrity_error` response that does not expose corrupt data.
- Uses the injected server time as the snapshot cutoff and its Asia/Shanghai date for future
  `as_of` validation.
- Registers the service in application lifespan and exempts the read-only cockpit GET from
  the runtime write lock.

## TDD evidence

1. Added `apps/api/tests/a_shares/test_cockpit.py` before production code.
2. Initial run failed during collection with
   `ModuleNotFoundError: qibao_api.a_shares.cockpit`.
3. Added the minimal aggregate and contracts; four service tests passed.
4. Added route tests before route/dependency implementation.
5. Route test collection failed because `get_a_share_cockpit_service` did not exist.
6. Added dependency, route, lifecycle wiring, and error shielding; target tests passed.
7. Added a read-only regression test that makes `candidates()` raise if called. It failed
   against the first implementation, then passed after membership derivation moved to the
   persisted phase advice.

## Verification

- Target tests: `30 passed`.
- Final full API suite after the read-only membership refinement: `523 passed`.
- Ruff: `All checks passed!`.
- `git diff --check`: no whitespace errors (only Git CRLF conversion warnings).
- Mojibake scan over touched Chinese source/test files: no matches.

## Concerns and decisions

- The brief presents a synchronous `get()` signature, but the existing diagnosis service is
  async. The cockpit method is async so the route does not create a nested event loop or
  bypass the established FastAPI lifecycle.
- One target-suite run failed while DuckDB opened the Chinese workspace path with a transient
  `UnicodeDecodeError`; an immediate identical rerun passed all 30 tests. This appears to be
  an existing Windows/DuckDB path issue rather than cockpit behavior, but remains a test
  environment risk.
- There is no persisted fund or backtest result repository in the current application. The
  response therefore reports the two binding explicit unavailable reasons and performs no
  speculative computation.
