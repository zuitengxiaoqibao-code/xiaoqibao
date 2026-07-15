# Task 2 Report

## Status

Complete.

## Commit

This implementation commit: `feat(decisions): generate evidence-backed premarket advice`.

## Files

- `apps/api/src/qibao_api/zhongshu/decision_ai.py`
- `apps/api/src/qibao_api/zhongshu/premarket_decision.py`
- `apps/api/tests/zhongshu/test_decision_ai.py`
- `apps/api/tests/zhongshu/test_premarket_decision.py`
- `apps/api/src/qibao_api/shangshu/scheduler.py`
- `apps/api/tests/shangshu/test_scheduler.py`
- `.superpowers/sdd/task-2-report.md`

## TDD Evidence

RED command:

```powershell
.venv\Scripts\python.exe -m pytest apps/api/tests/zhongshu/test_decision_ai.py apps/api/tests/zhongshu/test_premarket_decision.py apps/api/tests/shangshu/test_scheduler.py -q
```

RED result: collection failed with two expected `ModuleNotFoundError` errors for
`qibao_api.zhongshu.decision_ai` and `qibao_api.zhongshu.premarket_decision` before
either production module existed.

GREEN command:

```powershell
.venv\Scripts\python.exe -m pytest apps/api/tests/zhongshu/test_decision_ai.py apps/api/tests/zhongshu/test_premarket_decision.py apps/api/tests/shangshu/test_scheduler.py -q
```

GREEN result: `22 passed in 1.55s`.

Broader regression result: `396 passed in 28.27s`.

## Design Decisions And Deviations

- Added frozen timestamped envelopes for candidate, compliance, and market-risk inputs because the
  existing candidate board has no capture timestamp.
- Kept all service dependencies injected and duck-typed; no application globals are imported.
- Provider output uses an extra-forbidden schema and a whole-result validation gate. One synchronous
  attempt produces distinct invalid-output and provider-error counters.
- Persisted AI provider, model, prompt version, generation time, evidence IDs, and counters in each
  frozen advice payload. Credentials remain private to the gateway and are absent from requests,
  representations, results, and repository payloads.
- The source input hash excludes AI output, so identical deterministic source inputs return the prior
  aggregate without another provider call. Changed source inputs append through the Task 1 chain.
- Candidate factor membership is the only positive support used to establish `observe`; headline text
  never changes direction. Candidate-associated events with deterministic risk markers are contrary
  evidence and downgrade the action, while direction-unknown news remains at cycle reference level.
- News and interpretations are candidate/A-share scoped before canonical hashing and snapshot references.
- Scheduler integration records briefing completion before running the optional decision workflow and
  uses a distinct decision job stream for its started/completed/failed lifecycle.

## Self Review

- Confirmed Task 2 emits only A-share `observe`, `wait`, or blocked/no-advice outcomes and never plans.
- Confirmed all evidence and source timestamps stored in the aggregate are at or before the window end.
- Confirmed missing/future required inputs block advice and AI failure retains deterministic advice.
- Confirmed repository serialization is the return boundary, preventing first-run/idempotent type drift.
- Confirmed no API key or raw provider response is persisted.

## Concerns

- Direction-unknown news is intentionally excluded from advice evidence until a deterministic direction
  contract becomes available.

## Review Fix Evidence

Review RED command:

```powershell
.venv\Scripts\python.exe -m pytest apps/api/tests/zhongshu/test_decision_ai.py apps/api/tests/zhongshu/test_premarket_decision.py apps/api/tests/shangshu/test_scheduler.py -q
```

Review RED result: `18 failed, 19 passed in 2.14s`. Failures covered headline-driven advice,
risk-event evidence placement, unrelated/bond news hashing, evidence-number reuse, expanded prohibited
semantics, and scheduler decision-job projection.

Review GREEN result: `37 passed in 2.00s`.

Final review verification: focused `37 passed in 1.83s`; full API `411 passed in 27.17s`;
Ruff clean; mojibake scan empty; `git diff --check` clean.
