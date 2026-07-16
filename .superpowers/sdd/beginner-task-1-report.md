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

- Superseded by the review-fix section below. Legacy SQLite plan rows remain on disk by design and are projected to plan-free research history without being modified.

## Review Fixes

The initial Task 1 review failed because legacy plan-bearing decision rows could not be loaded, paper-only domain modules and compliance registration remained, simulation-gate fields remained in response contracts, and obsolete tests had been skipped or type-suppressed.

### Additional RED Evidence

Focused command:

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/shangshu/test_decision_repository.py::test_legacy_plan_bearing_cycle_projects_to_research_history_and_allows_append apps/api/tests/libu_compliance/test_main_lifespan.py::test_lifespan_injects_guarded_production_sources_and_closes_compliance apps/api/tests/contracts/test_decision.py::test_advice_contract_has_no_simulation_gate_fields apps/api/tests/test_app.py::test_paper_only_modules_are_deleted -q`

Result: `4 failed`. The failures reproduced legacy `simulated_plan` validation failure, remaining `paper_orders` registration, remaining `simulation_gate` contract field, and remaining paper-only modules.

The first full API fix run also exposed a normal-row decimal coercion regression (`485 passed, 1 failed`). A focused regression confirmed the root cause and the compatibility projection was restricted to legacy plan-bearing rows.

### Fixes Applied

- Added a real legacy SQLite fixture with stored plan-bearing advice and a plan row. The repository verifies original hashes, projects only the returned domain object to deterministic `observe`, removes plan/gate keys, preserves the stored rows, and appends the next cycle without breaking lineage.
- Removed `paper_orders` compliance registration and quote authorization.
- Deleted trading contracts, paper schema, allocation policy, order-risk rules, and their exclusive tests.
- Removed `SimulationGateAudit`, `simulation_gate`, gate handling, TypeScript gate types, paper CSS, and order-rejection UI contracts.
- Rewrote cockpit, decision-workbench, research-route, and intraday tests around research-only advice, evidence, history, stale isolation, stock switching, filtering, and append behavior.
- Removed all file-wide TypeScript suppression and all Task 1 skips. Removed dead paper fakes and execution/risk parameters.

### Final GREEN Evidence

- Legacy compatibility plus normal-row regression: `2 passed`.
- Focused affected backend suites: `117 passed`.
- Full API suite with ASCII `QIBAO_DATA_DIR`: `486 passed`, no skips.
- Full web suite: `89 passed`, no skips.
- Web TypeScript and Vite production build: passed, 1,604 modules transformed.
- Ruff on all touched Python files: `All checks passed!`.
- Full non-legacy production scan for paper accounts/orders/fills/positions/ledger, allocation, risk decisions, and simulation gates: `NO_NONLEGACY_PAPER_OR_GATE_REFERENCES`.
- Mojibake scan: `NO_MOJIBAKE_MATCHES`.

### Final Concerns

- The repository contains three literal legacy simulation field names in one compatibility projection method. They are necessary to recognize and strip old payloads and are not part of new models, responses, or writes.
- Full API verification uses an ASCII temp `QIBAO_DATA_DIR` because DuckDB on this Windows environment intermittently fails to decode the Chinese workspace path; the isolated failing lifespan tests pass, and the full suite passes with the ASCII data directory.
