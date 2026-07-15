# Task 1 implementation report

## Status

Implemented the A-share instrument directory and `GET /api/v1/a-shares/search`.
The implementation is scoped to Task 1 only.

## RED evidence

The directory and route tests were added before production code.

Command:

```powershell
.venv\Scripts\python.exe -m pytest apps/api/tests/a_shares/test_instrument_directory.py apps/api/tests/routes/test_research.py -q
```

Observed result: collection failed with two `ModuleNotFoundError` errors for
`qibao_api.a_shares.instrument_directory`. This was the expected failure because the new
module did not exist.

After the first minimal implementation, the tests exposed an invalid test assumption:
`000300` is ambiguous in a code-only model because the `000` namespace is also used by
Shenzhen shares. The index isolation case was corrected to the unambiguous index code
`399001`; convertible bond `113065` remained in the parameterized rejection test.

## GREEN implementation

- Added frozen `AShareInstrument` validation with A-share code, exchange, aware timestamp,
  and quote-quality constraints.
- Added a SQLite append-only observation table. `resolve()` and `search()` select the latest
  observation per symbol without deleting history.
- Added deterministic ranking: exact code, name prefix, then symbol.
- Added dependency accessors for the singleton directory and Tencent quote source.
- Added `/api/v1/a-shares/search` with non-blank `q`, `limit` in `1..20`, A-share-only output,
  server time, and source status.
- Exact valid codes absent from the named directory are verified with Tencent. Verification
  failures return empty items with `source_status="unavailable"`.
- Name queries use only locally observed names and never invoke Tencent or synthesize names.
- Startup seeds locally known bar symbols as code-only unavailable observations. These are
  never returned as named results without successful Tencent verification.
- Successful Tencent exact-code lookups append the observed company name and quality.
- The directory connection is closed in the existing lifespan shutdown block.
- Naive Tencent timestamps are interpreted in `Asia/Shanghai` before entering the aware
  directory model.

## GREEN evidence

Focused implementation plus lifecycle verification:

```text
28 passed in 22.09s
All checks passed!
```

The final binding task command passed `25` tests in `5.69s`; its matching Ruff command
reported `All checks passed!`.

The encoding scan over all touched Chinese-bearing source and test files returned no
replacement-character or known mojibake-pattern matches.

## Self-review

- Convertible bonds and unambiguous index namespaces fail `AShareCode` validation before
  persistence or external lookup.
- Exact-code verification validates the returned quote through `AShareInstrument`; a wrong
  or non-A-share symbol cannot be persisted.
- SQLite access is serialized with an `RLock`, and `check_same_thread=False` matches FastAPI's
  sync dependency/threadpool execution model.
- Equal timestamps are deterministic because the append id is a secondary descending key.
- Route fallback catches external adapter and payload errors and converts them to the required
  non-500 unavailable response.
- A code-only bar seed is deliberately represented with `name == symbol`; route logic treats
  that state as unresolved and requires Tencent verification before returning it.
- No Task 2 code, contracts, or behavior were added.

## Residual concerns

- Shanghai index identifiers can overlap Shenzhen share numbers when exchange is omitted.
  This endpoint intentionally interprets six-digit exact codes through the existing A-share
  market-prefix rule; unambiguous index namespaces such as `399xxx` are rejected.
- The directory is local and append-only, so long-running installations may eventually need
  retention or compaction policy. That is outside Task 1.
- A full `apps/api/tests` run passed 508 tests and failed one unrelated global-app startup:
  DuckDB raised `UnicodeDecodeError` while opening `.runtime/market.duckdb` under the Chinese
  workspace path. The failing test passed immediately in isolation, and the binding Task 1
  suite remained green. No unrelated DuckDB/storage change was made.

## Review fixes: RED evidence

The review regressions were written before the corrective production edits.

Combined red command:

```powershell
.venv\Scripts\python.exe -m pytest apps/api/tests/a_shares/test_instrument_directory.py apps/api/tests/routes/test_research.py apps/api/tests/libu_compliance/test_main_lifespan.py -q
```

Observed result: `4 failed, 30 passed in 7.08s`.

- Direct observation of `000300` did not raise, proving the code regex alone admitted the
  overlapping index identifier.
- A mismatched upstream `600002` payload was returned for requested `600001`.
- `sqlite3.ProgrammingError` was swallowed and mapped to an unavailable response.
- A seed failure after directory construction left the directory open.

The first mixed-offset regression data accidentally had the same lexical and chronological
ordering. It was corrected before production edits so the later UTC instant sorted lexically
before the earlier `+09:00` instant. Its isolated red run then failed with `1 failed in 0.53s`,
resolving the earlier observation instead of the later instant.

## Review fixes: GREEN evidence

- `AShareInstrument.observed_at` is canonicalized to UTC before persistence, so the existing
  ISO text ordering is chronological across input offsets.
- `000300` is explicitly classified as a non-equity identifier. This avoids a broad numeric
  prefix rule that would reject legitimate Shenzhen equities sharing Shanghai index numbers.
- Exact-code lookup compares `quote.symbol` with the requested symbol before construction,
  observation, or response.
- The route catches only expected `httpx.HTTPError` and quote payload/model `ValueError` while
  directory persistence executes outside that mapping; SQLite failures now surface.
- Directory construction and bar seeding now occur directly inside the existing lifespan
  cleanup `try/finally`, including failures before `yield`.
- Two independent directory connections completed interleaved observe/search loops and both
  resolved the same latest observation. Existing SQLite transaction serialization was
  sufficient, so no speculative journal-mode change was added.

Fresh verification after the review fixes:

```text
34 focused and lifecycle tests passed in 6.34s
515 full API tests passed in 20.43s
Ruff: All checks passed!
Mojibake scan: no matches
git diff --check: clean
```

## Numeric payload review fix

### RED

Added a route regression whose source delegates to the real `parse_tencent_quote()` with a
50-field Tencent-shaped payload containing `price="not-a-number"`.

```powershell
.venv\Scripts\python.exe -m pytest apps/api/tests/routes/test_research.py::test_exact_code_maps_malformed_tencent_numeric_payload_to_unavailable -q
```

Observed: `1 failed in 1.58s`; `Decimal(fields[3])` raised
`decimal.InvalidOperation` through the route.

### GREEN

The expected external quote failure tuple now includes `DecimalException`. Directory
persistence remains outside the tuple, so storage and programming failures are not hidden.

Boundary verification:

```text
2 passed in 1.22s
```

This jointly covered the malformed real-parser path and the existing
`sqlite3.ProgrammingError` propagation regression.

Final verification:

```text
35 focused and lifecycle tests passed in 6.18s
516 full API tests passed in 33.60s
```

The first full run passed 515 tests before the known DuckDB Unicode workspace-path startup
failure occurred in an unrelated health test. The clean full run used the same tests with
`QIBAO_DATA_DIR` set to an ASCII-only temporary runtime path, avoiding that DuckDB/Windows
environment issue.
