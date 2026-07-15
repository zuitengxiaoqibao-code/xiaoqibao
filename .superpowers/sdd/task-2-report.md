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

## Review fixes

Follow-up review changes were implemented with regression tests:

- Added `persist: bool = True` to `AShareDiagnosisService.diagnose()`. The cockpit passes
  `persist=False`, while the normal diagnosis endpoint retains its existing persisted
  snapshot behavior. A recording-repository test proves both sides of this boundary.
- Market and finance authorization failures now become data-unavailable results at their
  individual source boundary. Market failure affects market/valuation while local bars,
  trend, news, and industry remain available; finance failure affects fundamentals only.
- Decision filtering now requires both the selected symbol and `AssetKind.A_SHARE`, including
  a defensive regression for heterogeneous repository data sharing the same symbol string.
- A cycle is excluded when any `source_observed_at` is after the server cutoff, in addition
  to the existing generated/advice/evidence cutoff checks.
- Current advice is resolved first by latest creation time. A latest `invalidated` record
  removes that horizon from current advice; candidate membership is then derived only from
  this effective current set, so removed advice cannot keep a stock on the candidate board.
- Review-focused A-share and route suite: `73 passed`.
- Final full API suite after review fixes: `529 passed`.
