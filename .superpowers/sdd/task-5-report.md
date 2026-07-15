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
- Connected the A-share research workspace to the same URL-backed global selection, including direct URL diagnosis restore and candidate-to-global selection updates.
- Corrected the cockpit quote DTO mapping to prefer backend `market.metrics.price`, with an explicit legacy `latest_price` fallback.
- Isolated retained cockpit snapshots by `(symbol, live|historical date)` so only same-context refresh failures may show stale data.
- Preserved specific unavailable explanations alongside normalized section reason codes.
- Added cutoff-aware instrument identity resolution; historical cockpits cannot use an identity observed after their snapshot cutoff.

## TDD Evidence

- Added failing tests first for news selection/filtering, stale response isolation, backtest default/edit behavior, cross-workspace deep links, browser history, and bond symbol removal.
- Focused final-review tests: `43 backend` and `19 frontend` passed after red/green implementation.
- Full frontend suite: `107 passed`.

## Verification

- API tests: `532 passed in 40.24s` with ASCII-only `QIBAO_DATA_DIR`.
- Ruff: all checks passed.
- Frontend tests: `107 passed`.
- Frontend production build: TypeScript and Vite build passed (`1606 modules transformed`).
- Mojibake scan: no matches.
- `git diff --check`: clean.

Browser acceptance at `1440x900` and `390x844` is intentionally left to the controller as requested.
