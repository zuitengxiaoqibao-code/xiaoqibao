# Task 3 Implementation Report

## Scope

- Added an A-share-only selected instrument provider with URL restoration, pushState updates, popstate handling, and frontend validation aligned with the backend A-share code contract.
- Added the candidate/search/watchlist selector with 250 ms name debounce, immediate exact-code lookup, deterministic initial candidate selection, explicit-selection stability, stale search isolation, and the fixed `qibao.a_share.watchlist.v1` key.
- Added stock cockpit API/types consumed by later cockpit UI work.
- Mounted the provider in `App` and composed the selector beside the existing three-phase workbench without changing convertible-bond state or Task 4 cockpit rendering.
- Added responsive selector styling with an 11 px text floor.

## TDD Evidence

- RED: the provider and selector suites first failed because their production modules did not exist.
- RED: the first-candidate initialization test then failed with a missing URL symbol before the one-time initialization behavior was added.
- GREEN: all focused and full frontend suites pass.

## Verification

- `pnpm --filter @qibao/web exec vitest run src/features/instrument-selection/SelectedInstrumentProvider.test.tsx src/features/stock-cockpit/StockSelector.test.tsx src/features/dashboard/Dashboard.test.tsx` -> 3 files, 20 tests passed.
- `pnpm --filter @qibao/web test` -> 14 files, 65 tests passed.
- `pnpm --filter @qibao/web build` -> TypeScript and Vite production build passed.
- `rg -n '�|锟|烫烫|\?\?\?' apps/api/src/qibao_api apps/api/tests apps/web/src README.md` -> no matches.
- `git diff --check` -> passed; only Git line-ending notices were emitted.

## Risks / Follow-up

- Watchlist storage intentionally contains symbols only; display metadata remains API-owned.
- Candidate rows do not invent names because the existing candidate contract does not provide them; verified names appear in search results.
- Task 4 still owns the detailed selected-stock cockpit rendering and request-isolation UI.

## Commit

- `feat(web): add global A-share selection` (this commit)
