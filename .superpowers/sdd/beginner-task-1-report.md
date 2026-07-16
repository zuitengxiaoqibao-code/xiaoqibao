# Beginner Cockpit Task 1 Report

## Status

DONE_WITH_CONCERNS

Paper trading and simulation-plan runtime behavior have been removed end to end. Existing SQLite files and any historical plan rows are not deleted or migrated; the runtime neither reads nor writes the legacy plan table.

## Files Changed

- Deleted the complete `apps/web/src/features/paper-trading/` feature.
- Deleted the paper route, broker, service, simulation-plan builder, and paper repository.
- Deleted paper/broker/service/concurrency/repository/simulation-plan tests whose subject no longer exists.
- Removed paper startup state, router registration, dependencies, shutdown, backup verification, and App/Dashboard wiring.
- Refactored post-close context/review to use decision and audit repositories only.
- Removed `SimulationPlan`, `simulated_plan`, `simulation_plan_id`, aggregate plan collections, plan serialization, and plan UI/types.
- Refactored decision persistence to store advice only while remaining compatible with an existing legacy schema without reading or writing legacy plan rows.
- Updated A-share assessment/cockpit, intraday monitoring, decision responses, risk status, and affected tests.
- Added `apps/api/tests/test_app.py` and dashboard removal coverage.

## RED Evidence

Command:

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/test_app.py apps/api/tests/routes/test_paper.py -q`

Result: `2 failed, 2 passed`. The removal assertion failed because `/api/v1/paper` was registered. The decision assertion initially also exposed a test setup error because the application lifespan state was not initialized; the final focused test uses explicit dependency overrides.

Command:

`pnpm --filter @qibao/web exec vitest run src/features/dashboard/Dashboard.test.tsx`

Result: `1 failed, 19 passed`. The failure found `<section class="paper-panel">` with the paper-trading heading.

## GREEN Evidence

Focused API:

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/test_app.py -q`

Result: `2 passed`.

Required backend broad suite:

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/test_app.py apps/api/tests/zhongshu apps/api/tests/shangshu -q`

Result: `124 passed, 10 skipped`.

Required web suite:

`pnpm --filter @qibao/web test`

Result: `107 passed, 13 skipped`.

Full API suite:

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests -q`

Result: `523 passed, 19 skipped`.

Production web build:

`pnpm --filter @qibao/web build`

Result: TypeScript and Vite build succeeded; 1,604 modules transformed.

Removed-runtime scan:

`rg` over `apps/api/src/qibao_api` and `apps/web/src` for paper repository/service/routes, paper-trading imports, `SimulationPlan`, `simulated_plan`, and `simulation_plan_id`.

Result: `NO_REMOVED_RUNTIME_REFERENCES`.

Mojibake scan:

`rg` over touched API/web source and tests for common UTF-8 mojibake markers and repeated question marks.

Result: `NO_MOJIBAKE_MATCHES`.

## Self Review

- No paper route or service is registered at startup.
- Decision response slots contain advice/evidence and no plan fields.
- New decision databases do not create a plan table. Existing databases keep their old table untouched; compatibility inserts set only the legacy cycle count column to zero when that column exists.
- Intraday persistence no longer builds, compares, or stores plans.
- Post-close attribution uses market outcomes and audit findings, not simulated executions or paper risk decisions.
- The dashboard, decision workbench, and stock cockpit expose no paper account or numeric plan UI.
- No unrelated Task 2-6 implementation was added.

## Concerns

- Nineteen legacy API test cases and thirteen legacy web test cases are skipped because they exclusively asserted the deleted simulation-plan product. Remaining suites and builds pass.
- Legacy SQLite plan rows remain on disk by design and are ignored by the runtime.
