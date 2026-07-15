# Task 5 Implementation Report

Base commit: `6677263`

## Delivered

- Preserved the selected A-share `symbol` across dashboard, A-share research, news, risk, compliance, audit, and backtest routes.
- Added production routes for `/risk`, `/compliance`, `/audit`, and `/backtest`, including browser history restoration.
- Removed `symbol` when entering `/convertible-bonds`; the bond workspace does not consume A-share selection state.
- Displayed the selected A-share in news; governance pages explicitly identify their data as global or asset-level and show any A-share code only as navigation context.
- Filtered news events to the selected A-share while retaining market-wide events with no instrument binding; isolated stale news responses after same-route symbol changes.
- Made backtest default to the selected A-share without overwriting a symbol explicitly edited by the user. Input changes abort and invalidate older requests, results identify their own symbol, and bond/index codes are rejected.
- Updated README and V1 roadmap with candidate/search/watchlist workflow, explicit degradation behavior, asset isolation, observation-only boundary, and current completion state.

## TDD Evidence

- Added failing tests first for news selection/filtering, stale response isolation, backtest default/edit behavior, cross-workspace deep links, browser history, and bond symbol removal.
- Focused review-fix tests: `29 passed` after red/green implementation.
- Full frontend suite: `105 passed`.

## Verification

- API tests: `531 passed in 50.01s` with ASCII-only `QIBAO_DATA_DIR`.
- Ruff: all checks passed.
- Frontend tests: `105 passed`.
- Frontend production build: TypeScript and Vite build passed (`1606 modules transformed`).
- Mojibake scan: no matches.
- `git diff --check`: clean.

Browser acceptance at `1440x900` and `390x844` is intentionally left to the controller as requested.
