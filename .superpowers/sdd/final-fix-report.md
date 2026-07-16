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
