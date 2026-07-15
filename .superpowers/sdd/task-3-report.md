# Task 3 Implementation Report

## Scope

- Added an A-share-only selected instrument provider with URL restoration, pushState updates, popstate handling, and frontend validation aligned with the backend A-share code contract.
- Added the candidate/search/watchlist selector with 250 ms name debounce, immediate exact-code lookup, deterministic initial candidate selection, explicit-selection stability, stale search isolation, and the fixed `qibao.a_share.watchlist.v1` key.
- Added stock cockpit API/types consumed by later cockpit UI work.
- Mounted the provider in `App` and composed the selector beside the existing three-phase workbench without changing convertible-bond state or Task 4 cockpit rendering.
- Added responsive selector styling with an 11 px text floor.
- Review fixes centralize same-tab navigation notifications so the provider always re-reads the authoritative URL, including Dashboard route changes that remove `symbol`.
- Corrected the cockpit phase contract to the backend `StockPhaseHistory` and `DecisionVersion` payloads.
- Added candidate polling/manual refresh, retryable search errors, independent watchlist identity restoration, search-result watchlist controls, and complete tab ARIA/keyboard behavior.
- Candidate identity is resolved through the search API. Because neither the candidate nor search contract contains a live price/current change, those fields are explicitly unavailable; the five-day return remains separately and accurately labeled.
- Second review fixes invalidate search generations at query-change time, guard candidate responses by generation and mount lifetime, retain retryable watchlist identity errors, sanitize persisted watchlists with the shared A-share validator, and restrict tab keys to prevented horizontal arrows.

## TDD Evidence

- RED: the provider and selector suites first failed because their production modules did not exist.
- RED: the first-candidate initialization test then failed with a missing URL symbol before the one-time initialization behavior was added.
- RED review cycle: URL same-tab navigation, independent watchlist recovery, search retry, search-result watchlist, truthful quote labels, polling stability, and tab keyboard/ARIA tests all failed against the initial implementation before their fixes.
- RED second review cycle: identity error/retry, polluted localStorage cleanup, stale candidate ordering, and horizontal key default-prevention tests failed before implementation. A deferred search regression fixes the debounce-window generation boundary.
- GREEN: all focused and full frontend suites pass.

## Verification

- `pnpm --filter @qibao/web exec vitest run src/features/instrument-selection/SelectedInstrumentProvider.test.tsx src/features/stock-cockpit/StockSelector.test.tsx src/features/dashboard/Dashboard.test.tsx` -> 3 files, 32 tests passed.
- `pnpm --filter @qibao/web test` -> 14 files, 77 tests passed.
- `pnpm --filter @qibao/web build` -> TypeScript and Vite production build passed.
- `rg -n '�|锟|烫烫|\?\?\?' apps/api/src/qibao_api apps/api/tests apps/web/src README.md` -> no matches.
- `git diff --check` -> passed; only Git line-ending notices were emitted.

## Risks / Follow-up

- Watchlist storage intentionally contains symbols only; identity metadata is restored through exact-code search and missing identity is visibly degraded.
- Live price and current change remain explicitly unavailable until an API contract exposes them; factor close and five-day return are not presented as live data.
- Task 4 still owns the detailed selected-stock cockpit rendering and request-isolation UI.

## Commit

- `f77ce34 feat(web): add global A-share selection`
- `0761802 fix(web): harden global A-share selection`
- `fix(web): close A-share selector races` (second review-fix commit)
