# Task 5 Implementation Report

Base commit: `6677263`

## Delivered

- Preserved the selected A-share `symbol` across dashboard, A-share research, news, risk, compliance, audit, and backtest routes.
- Added production routes for `/risk`, `/compliance`, `/audit`, and `/backtest`, including browser history restoration.
- Removed `symbol` when entering `/convertible-bonds`; the bond workspace does not consume A-share selection state.
- Displayed the selected A-share in news and governance workspaces.
- Filtered news events to the selected A-share while retaining market-wide events with no instrument binding; isolated stale news responses after same-route symbol changes.
- Made backtest default to the selected A-share without overwriting a symbol explicitly edited by the user.
- Updated README and V1 roadmap with candidate/search/watchlist workflow, explicit degradation behavior, asset isolation, observation-only boundary, and current completion state.

## TDD Evidence

- Added failing tests first for news selection/filtering, stale response isolation, backtest default/edit behavior, cross-workspace deep links, browser history, and bond symbol removal.
- Focused news tests: `4 passed` after red/green implementation.
- Full frontend suite: `101 passed`.

## Verification

- API tests: `531 passed in 43.72s` with ASCII-only `QIBAO_DATA_DIR`.
- Ruff: all checks passed.
- Frontend tests: `101 passed`.
- Frontend production build: TypeScript and Vite build passed (`1606 modules transformed`).
- Mojibake scan: no matches.
- `git diff --check`: clean.

Browser acceptance at `1440x900` and `390x844` is intentionally left to the controller as requested.
