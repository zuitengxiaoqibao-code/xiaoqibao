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
