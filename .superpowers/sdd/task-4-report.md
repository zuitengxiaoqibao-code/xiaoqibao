# Task 4 Implementation Report

Status: DONE

## Implemented

- Added a conclusion-first single-stock cockpit with instrument identity, quote time, quote quality, deterministic intraday-first advice, evidence, contrary evidence, risks, and invalidation conditions.
- Kept the action boundary conservative: the cockpit API does not expose reciprocal plan/readiness records, so the UI explicitly renders observation-only and never infers a simulation plan.
- Added all ten fixed data sections with Chinese metric labels, explicit degradation reasons, source, observation time, and snapshot identifiers.
- Added a selected-symbol-only three-phase timeline with ordered version metadata, advice lineage, changed fields, prior advice, trigger evidence, and postclose attribution fallback.
- Added AbortController plus request generations. Switching symbols never renders the prior symbol, stale responses cannot win, and a same-symbol refresh failure retains the last successful snapshot with an explicit stale warning.
- Integrated the cockpit with the existing selector on the dashboard while preserving the prior DecisionWorkbench fallback behavior.
- Added responsive 320px selector plus fluid content layout, single-column behavior below 900px, mobile constraints, and an 11px minimum for all new dense text.

## Tests

Red phase:

```powershell
pnpm --filter @qibao/web test -- StockDecisionCockpit.test.tsx PhaseTimeline.test.tsx
```

Failed because the new cockpit and timeline modules did not exist.

Final focused/full frontend command (the repository Vitest script runs the full suite):

```powershell
pnpm --filter @qibao/web test -- StockDecisionCockpit.test.tsx StockSelector.test.tsx DecisionWorkbench.test.tsx Dashboard.test.tsx
```

Result: 16 files passed, 86 tests passed.

Production build:

```powershell
pnpm --filter @qibao/web build
```

Result: TypeScript and Vite production build passed, 1606 modules transformed.

Safety checks:

```powershell
rg -n '�|锟|烫烫|\?\?\?' apps/api/src/qibao_api apps/api/tests apps/web/src README.md
git diff --check
```

Result: no mojibake matches; diff check passed.

## Concerns

None. Browser viewport acceptance remains Task 5 as planned.

## Review Fixes

Review findings were addressed in a second TDD pass:

- The existing `DecisionWorkbench` now remains mounted below the stock cockpit, preserving polling, phase tabs, historical dates, degradation semantics, and full authoritative plan rendering.
- Partial and stale sections render their degradation reason.
- Timeline evidence includes source and observation time. Plain-language explanation is labeled as explanation and is never presented as postclose attribution; the missing backend attribution field is stated explicitly.
- Header quote time and quality come from the market section. Instrument-directory observation time is no longer treated as a market timestamp.
- Frontend DTOs now match `AShareInstrument`, `AdviceCard`, `SimulationGateAudit`, and `SimulationPlan`, including all nullable and required fields.
- The cockpit only displays a simulation-plan reference when action, plan reference, reciprocal risk reference, and all immutable gate fields pass. It does not invent plan details absent from the cockpit API.
- Contrary evidence includes source and observation time, and candidate membership is visible as short-term, swing, or not-current.

Review-fix verification:

```powershell
pnpm --filter @qibao/web test
pnpm --filter @qibao/web build
rg -n '�|锟|烫烫|\?\?\?' apps/api/src/qibao_api apps/api/tests apps/web/src README.md
git diff --check
```

Result: 16 files and 90 tests passed; production build passed; encoding and diff checks passed.

## Shared-State Review Fixes

The final review identified two split-brain risks. They were fixed with one dashboard-owned state model:

- `DecisionWorkbench` accepts the selected A-share and filters every phase's advice, evidence, plans, readiness, deltas, and change stream by both `asset="a_share"` and symbol. A missing selection and a selected stock with no records have explicit empty states.
- Dashboard owns the shared `asOf` date and refresh generation. Historical date changes drive both endpoints. `DecisionWorkbench` remains the only polling clock; polling, its refresh button, and the cockpit refresh button advance the same generation so both views refresh together without a second timer.
- Cockpit continues to abort old requests and reject old generations, while workbench filtering changes synchronously with selection. A previous stock cannot remain visible after switching.

Added regression coverage for mixed-asset/mixed-symbol filtering, historical-date coordination, polling coordination, manual-refresh coordination, and existing stale-response isolation.

Final verification:

```powershell
pnpm --filter @qibao/web test
pnpm --filter @qibao/web build
rg -n '�|锟|烫烫|\?\?\?' apps/api/src/qibao_api apps/api/tests apps/web/src README.md
git diff --check
```

Result: 16 files and 94 tests passed; production build passed; encoding and diff checks passed.

## Live And History Mode Fixes

- Replaced the historical-mode ref with render state so entering history immediately tears down the live polling interval, even when a historical response reports an open market session.
- Added an explicit `返回实时` command. It clears historical mode, requests the current endpoint, and restores polling only after returning live.
- Split the displayed trading date from the explicit historical API date. The current trading date can populate the date input without being sent back to the cockpit as `as_of`.
- The live cockpit now performs exactly one initial request with the API's default date behavior; only explicit history selection causes a dated cockpit request.

Added fake-timer coverage for stopped history polling and resumed live polling, plus a request-count assertion for the single live cockpit load.

Final verification after these fixes: 16 files and 96 tests passed; production build passed; encoding scan and `git diff --check` passed.
