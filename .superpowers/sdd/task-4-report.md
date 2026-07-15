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
