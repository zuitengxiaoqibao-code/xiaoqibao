# Task 5 implementation report

## Scope delivered

- Added current, historical, and scheduler-delegated manual decision routes.
- Added Beijing-time phase selection, closed-day fallback, explicit empty slots, integrity shielding, date validation, polling metadata, versions, advice, evidence, and plans.
- Added the configured decision database path, one lifespan-owned repository, dependencies, router registration, lifecycle close, backup inclusion, and verified repository reads during restore drills.
- Replaced the production root screen with a dense three-phase A-share workbench while preserving separate research, convertible-bond, department, news, and operations navigation.
- Added request sequence isolation, aggregate-only polling, operational states, evidence ordering, and reciprocal simulation-plan gating.
- Updated roadmap and README without claiming V1 completion.

## TDD record

Backend RED: route tests failed during collection because decision dependencies did not exist. The settings test then failed because `decision_database_path` did not exist. Existing lifespan tests exposed fixture compatibility after production composition was added.

Backend GREEN: route tests passed (`5 passed`), followed by the full backend suite (`480 passed`).

Frontend RED: the web suite failed to resolve the missing `DecisionWorkbench` module while pre-existing suites remained green.

Frontend GREEN: all `12` web test files and `46` tests passed; the TypeScript/Vite production build also completed.

## Safety self-review

- Routes never write snapshots directly; manual execution delegates to the scheduler.
- Integrity exceptions become a stable 503 response without repository error text or advice leakage.
- Missing data produces explicit empty or degraded states; no evidence or values are invented.
- Browser code calls only aggregate decision endpoints.
- Simulation plans require reciprocal advice, plan, risk, and compliance references.
- A-share and convertible-bond routes and models remain separate.
- Existing append-only triggers and verified repository reads remain authoritative.

## Visual self-review

- Uses the existing dark operations tokens, compact typography, hairline borders, Lucide icons, and restrained cyan/green/amber/red semantics.
- Desktop uses a primary column plus status rail; below 760px it becomes one column.
- Risks and contrary evidence precede any simulation plan.
- Global reduced-motion handling applies to the new view.

## Remaining acceptance

Browser acceptance was intentionally not performed per controller instruction. The controller must verify 1440x900 and 390x844 after independent review. Department workspaces and the final production audit remain outstanding, so V1 is not complete.

## Runtime composition completion

Follow-up RED evidence:

- `pytest apps/api/tests/shangshu/test_scheduler.py apps/api/tests/libu_compliance/test_main_lifespan.py -q` failed during collection with `ModuleNotFoundError: qibao_api.shangshu.decision_runtime`.
- The new tests require all-phase scheduler dispatch, manual phase delegation, concrete adapter instances, scheduler/runner identity, singleton repository identity, and lifecycle closure.

Follow-up GREEN evidence:

- Composition/lifecycle/manual-run tests passed: `15 passed`.
- Focused route, scheduler, phase-service, Tencent normalization, and lifecycle suite passed: `90 passed`.

Production composition now includes:

- Repository-backed A-share candidate/factor snapshots from the existing diagnosis service.
- Verified news evidence snapshots with cutoff enforcement.
- Compliance decisions from registered A-share source authorizations.
- Deterministic A-share market-risk state derived from candidate factor breadth, with open audit findings applied as an additional risk overlay; missing factor breadth degrades explicitly to `insufficient_data` without inventing a market state.
- A synchronous Tencent polling feed carrying real normalized price, change, volume, source timestamp, fetch timestamp, and source snapshot identity.
- A deterministic intraday evaluator that only updates observation advice from normalized quotes and never creates AI numbers or ungated plans.
- Repository-backed post-close outcome records that remain explicitly unverifiable when observation-only advice cannot establish a deterministic direction.
- Existing paper execution/risk decisions and audit findings passed directly to `PostcloseReviewService`.
- One `DecisionPhaseRunner` shared by scheduled and manual execution for premarket, intraday, and postclose.
- Explicit closure of both decision and intraday polling SQLite repositories.

## Fix Review

### RED evidence

- Backend review tests: `5 failed, 18 passed`.
- Failures proved that manual decision errors still returned a report/HTTP 200 and that market risk accepted only the audit repository.
- Frontend review tests initially produced one remaining failure after implementation: ArrowRight changed selection but did not synchronously transfer focus.
- The production build then rejected an imprecisely inferred test readiness map, preventing a false completion claim.

### GREEN behavior

- Simulation plans now require an API-provided `plan_readiness.ready=true`. The API derives readiness from stored quote, evidence, compliance, and risk gate states plus advice/plan/risk/compliance reciprocal references. Missing, blocked, rejected, or mismatched state keeps the UI observation-only.
- Intraday persistence freezes the original deterministic simulation gate into the append-only advice quantitative payload, so the browser does not reconstruct gate decisions.
- Market risk now derives availability and strong/range/weak state from real A-share candidate factor breadth. Open audit findings are an additive overlay; no findings no longer imply unavailable. Missing factor breadth explicitly yields `insufficient_data` and `market_factor_evidence_unavailable`.
- Partial, blocked, empty, AI-unavailable, retry, stale aggregate, next-check, and current focus/universe cadence states are distinct. Staleness uses only API `server_time`, aggregate `generated_at`, and `stale_after_seconds`.
- Phase tabs now have stable IDs, `aria-controls`, a labeled tabpanel, roving `tabIndex`, and Left/Right arrow focus navigation.
- Manual phase selection survives polling and date reloads; API auto-selection applies until the user deliberately selects a phase.
- Manual decision-run exceptions now return `None` from the scheduler after the failure is audited. The decision route maps this to HTTP 503 `decision_run_failed` instead of reporting delegated success.

### Focused GREEN evidence

- Backend route/scheduler/risk tests: `24 passed`.
- Frontend workbench plus existing web suites: `12 files, 52 tests passed`.
- Browser acceptance remains intentionally unperformed per controller instruction.

### Final verification

- Full backend: `488 passed`.
- Ruff: `All checks passed`.
- Full frontend: `12 test files, 52 tests passed`.
- TypeScript/Vite production build: passed.
- Mojibake/fallback-marker scan: no matches.
- `git diff --check`: passed.

## Final Cross-Task Review Fixes

### RED evidence

- Immutable safety tests failed `3` cases: persisted simulation advice accepted no gate, and both quantitative levels and persisted plans accepted tranche totals above `max_position`.
- Current-mode frontend polling regression test demonstrated that polling called the date-specific loader after the initial current response populated its date.
- Focused integration exposed `8` obsolete monitor fixtures that attempted to construct malformed planned advice without a passing immutable gate; the contract now rejects these producers before persistence.

### Implemented behavior

- The serialized production scheduler iteration now executes fixed briefing slots and `tick_intraday` together under the existing application write lock. Layered cadence therefore runs independently of completed fixed slots while the persisted PollState owns 60-second focus, 180-300-second universe, and 60/120/240/300 failure backoff.
- Intraday API advice is an authoritative materialized observation state folded across premarket plus every intraday delta. `delta_version`, `delta_advice`, and `delta_plans` remain separately exposed as the append-only change stream.
- Immutable `AdviceCard` validation requires a stored passing gate for simulated plans. Repository integrity additionally verifies risk and compliance references across advice, gate, and plan.
- Persisted PollState now supplies API mode, intervals, failure counts, last successes, next dues, and next-check timing. An absent state is explicit `uninitialized`; no interval is fabricated.
- `QuantitativeLevels` and `SimulationPlan` both enforce `sum(tranches) <= max_position`.
- Date-specific responses consult the trading calendar; an unconfirmed current date is closed/postclose, never open.
- Current-mode browser polling continues to call the current endpoint. The historical endpoint is used only after explicit date selection, and manual phase selection remains stable.

### Verification evidence

- Full backend: `492 passed`.
- Ruff: all checks passed.
- Full frontend: `12 files, 53 tests passed`.
- Production TypeScript/Vite build: passed.
- Browser acceptance was not performed, per controller instruction.
