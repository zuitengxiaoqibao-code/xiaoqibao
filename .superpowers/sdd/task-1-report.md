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
