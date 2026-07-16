# Task 1 Report

## Result

- Added an optional `cutoff` to `RepositoryCandidateFactorSource.candidates`.
- Premarket decisions now capture candidate input at the calculated `window_end`.
- Calls without a cutoff retain the injected clock behavior.
- The existing `universe_status == "ready"` history boundary remains unchanged.

## RED

Command:

```text
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/zhongshu/test_premarket_decision.py -q
```

Result: expected failure, `1 failed, 14 passed`. The new test failed with
`TypeError: RepositoryCandidateFactorSource.candidates() got an unexpected keyword argument 'cutoff'`.

## GREEN

Focused command:

```text
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/zhongshu/test_premarket_decision.py -q
```

Result: `15 passed in 0.79s`.

Related decision command:

```text
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/zhongshu apps/api/tests/shangshu -q
```

Result: `133 passed in 3.71s`.

Quality checks:

```text
apps/api/.venv/Scripts/python.exe -m ruff check apps/api/src apps/api/tests
rg -n "replacement-character|three-question-marks" <touched files>
git diff --check
```

Result: Ruff passed, the mojibake scan returned no matches, and `git diff --check` passed.

## Files

- `apps/api/src/qibao_api/shangshu/decision_runtime.py`
- `apps/api/src/qibao_api/zhongshu/premarket_decision.py`
- `apps/api/tests/zhongshu/test_premarket_decision.py`
- `.superpowers/sdd/task-1-report.md`

## Commit

`fix(decisions): freeze premarket candidate cutoff` (the commit containing this report)

## Self-review

- Scope is limited to Task 1.
- The explicit cutoff is timezone-aware because it is derived from the existing `window_end` calculation.
- Default runtime callers remain backward compatible.
- No history-readiness or decision-boundary checks were relaxed.

## Concerns

None.

## Review Fix: Real Cutoff Snapshot

The first implementation only set `captured_at` to the requested cutoff. Review correctly
identified that the underlying candidate service still read the current bar repository, so
late-ingested bars could be mislabeled as pre-cutoff evidence.

### RED

Combined candidate and storage regressions:

```text
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/zhongshu/test_premarket_decision.py apps/api/tests/a_shares/test_diagnosis.py apps/api/tests/storage/test_bar_repository.py -q
```

Result: expected `3 failed, 34 passed`. The failures showed that a legacy candidate port was
not rejected, `AShareDiagnosisService` did not accept cutoff, and `BarRepository` did not
filter by ingestion time.

Risk-source regression:

```text
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/shangshu/test_decision_runtime.py::test_market_risk_is_available_from_candidate_breadth_without_audit_findings -q
```

Result: expected `1 failed`; the candidate source recorded `None` instead of the risk cutoff.

An additional legacy port using `candidates(as_of, **kwargs)` failed the strengthened rejection
test (`1 failed`) before the implementation required an explicitly named `cutoff` parameter.

### GREEN

- Added the explicit `CutoffCandidateService` protocol.
- Explicit cutoff requests reject legacy `candidates(as_of)` ports before reading data.
- `AShareDiagnosisService.candidates` passes cutoff to both bar queries.
- `BarRepository` filters `symbols_with_history` and `latest_many` by `ingested_at <= cutoff`.
- Aware cutoffs are normalized to naive UTC for the DuckDB timestamp column.
- `RepositoryRiskSource` uses the same cutoff when it reads candidate breadth.
- Late execution still requests the fixed 09:25 China-time window end.
- Bars ingested after cutoff are excluded; replacement after cutoff safely removes the prior
  row from the historical view rather than exposing the replacement as old evidence.

Focused premarket verification:

```text
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/zhongshu/test_premarket_decision.py -q
```

Final result: `17 passed in 1.79s`.

Related A-share, Shangshu, and bar repository verification:

```text
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares apps/api/tests/shangshu apps/api/tests/storage/test_bar_repository.py -q
```

Final result: `136 passed in 8.98s`.

Quality verification:

```text
apps/api/.venv/Scripts/python.exe -m ruff check apps/api/src apps/api/tests
rg -n "replacement-character|three-question-marks" <touched files>
git diff --check
```

Result: Ruff passed, the mojibake scan returned no matches, and `git diff --check` passed.

### Review Self-check

- All bar-derived factor inputs now come from rows whose `ingested_at` is no later than cutoff.
- No code path can silently relabel an old-style current candidate read as a cutoff snapshot.
- No Task 2 behavior was added.

### Review Concerns

None.
