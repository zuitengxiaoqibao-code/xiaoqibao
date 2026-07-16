# Final Fix Report

## Status

All final-review blockers for on-demand A-share assessment are resolved.

## Corrections

- Historical cockpit requests now pass cutoff through diagnosis into bar, market,
  finance, and news reads. Candidate factor snapshots also pass their frozen cutoff.
- Daily bars are append-only observations. Existing primary-key databases migrate
  in place, and cutoff queries select the last observation available for each
  symbol and trading date.
- Deterministic `avoid` uses production-shaped missing-section, adverse-event,
  volatility, and drawdown metrics. Confidence is rule-specific rather than a
  fixed optimistic value.
- AI output must cite the complete assessment evidence set and is rejected when
  any free-text field contains prices, positions, buy/sell language, or stops.
- Cockpit responses include the bound authoritative `SimulationPlan` or null.
  The web client independently verifies reciprocal advice, plan, risk, and
  compliance references before showing frozen numerical levels, explicitly as
  simulation-only content.

## TDD Evidence

The new assessment, AI, and bar-version tests first failed with seven expected
behavioral failures. After implementation, the focused API set passed 139 tests.
Historical cutoff and legacy-schema migration regressions were then added and
included in the full suite.

## Verification

- API: `578 passed in 32.70s`
- Ruff: `All checks passed!`
- Web: `116 passed`
- TypeScript/Vite production build: passed
- Mojibake scan: no source/test/UI matches; only documentation lines containing
  the scan command itself matched
- `git diff --check`: passed

## Residual Concerns

- Append-only bar storage grows with every revision and needs normal retention
  and backup capacity monitoring; no destructive compaction was introduced.
- AI instruction filtering is deliberately conservative and may reject benign
  prose containing a price or percentage, degrading to deterministic output.

## Final Re-review Corrections

### Files changed

- `apps/api/src/qibao_api/a_shares/diagnosis.py`
- `apps/api/src/qibao_api/a_shares/assessment.py`
- `apps/api/src/qibao_api/storage/bar_repository.py`
- `apps/web/src/features/stock-cockpit/StockDecisionCockpit.tsx`
- `apps/api/tests/a_shares/test_diagnosis.py`
- `apps/api/tests/a_shares/test_assessment.py`
- `apps/api/tests/storage/test_bar_repository.py`
- `apps/web/src/features/stock-cockpit/StockDecisionCockpit.test.tsx`

### Tests added

- Verified risk news now flows through production diagnosis and cockpit contracts
  to an `avoid` assessment.
- Missing market and trend data remain a low-confidence `wait` even when several
  other sections are missing.
- Numeric plans stay hidden for false eligibility and each individually blocked
  or rejected authoritative gate.
- Parquet export contains only the repository-latest same-day bar revision.

### Commands and outputs

- Focused Python: `34 passed in 4.50s`.
- Web tests: `121 passed` across 16 files.
- Touched Python Ruff: `All checks passed!`.
- Web TypeScript/Vite production build: passed, 1606 modules transformed.
- Mojibake scan of every touched source and test file: no matches.
- `git diff --check`: passed.
