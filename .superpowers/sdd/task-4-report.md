# Task 4 implementation report

## Implementation

- Added immutable `AdviceOutcome` and `PostcloseReviewResult` contracts.
- Added `PostcloseReviewService.run(trading_date, now)`.
- Frozen review scope is limited to same-day premarket and intraday advice created no later than 15:00 China time.
- Market outcomes, simulated execution records, risk decisions, and East Factory findings are filtered to each advice's creation-to-close evidence window.
- Outcome status and attribution are assigned deterministically from the fixed allowed value sets.
- Missing market outcomes are classified as `unverifiable/data_unavailable`, never `wrong`.
- Only correct outcomes and untriggered unverifiable outcomes enter `next_day_observations`.
- Withdrawn outcomes are persisted as invalidated post-close advice with a withdrawal/revalidation reason.
- Every persisted derived advice contains the original advice id, original snapshot id, deterministic status, attribution, and canonical outcome-input hash.
- The complete post-close aggregate is appended through `DecisionRepository`, read back, and returned.
- Repeated runs with unchanged frozen inputs reuse the existing post-close cycle; review time is excluded from the deterministic aggregate input hash.
- Tightened `RepositoryPostcloseContextSource` so order outcomes and findings after market close are excluded even when the review runs later.

## TDD record

1. Initial focused test run failed during collection with `ModuleNotFoundError: qibao_api.zhongshu.postclose_review`, confirming the new behavior did not exist.
2. Implemented the minimum service and close cutoff; the focused suite passed with 4 tests.
3. Self-review identified review-time contamination of the aggregate input hash.
4. Added an idempotent-rerun regression test; it failed because the second run generated a different snapshot id.
5. Excluded `reviewed_at` from canonical aggregate inputs; the focused suite then passed with 5 tests.

## Test coverage

- Excludes advice created after the same-day close.
- Excludes market observations after close.
- Preserves original advice and snapshot references plus a 64-character canonical input hash.
- Maps unavailable market data to `unverifiable/data_unavailable` and retains it only while invalidation is untriggered.
- Maps wrong, invalidated, and risk-blocked outcomes to withdrawal/revalidation records.
- Persists a post-close decision aggregate through the repository interface.
- Does not append a new cycle for unchanged frozen inputs.
- Clamps the briefing post-close context at market close.

## Self-review

- Evidence window: all input collections are queried through close and filtered again per advice creation time through close. Late advice and late observations are ignored.
- Unavailable data: absence of an available market outcome takes the explicit `unverifiable/data_unavailable` branch before directional scoring.
- Immutable status: `AdviceOutcome` is a frozen model; optional AI is not consulted during status or attribution calculation.
- Persistence completeness: original references and outcome hash are copied into each derived advice; all derived records are written inside one post-close `DecisionCycleAggregate` through `append_cycle`, then read back.
- Append-only behavior: unchanged canonical inputs return the stored aggregate; changed inputs advance the phase sequence and previous-snapshot link.

## Concerns

- Production market outcome adapters must supply records with `advice_id`, observation time, availability, direction, and invalidation state. Task 4 defines and consumes that boundary but does not add a provider adapter.
- Existing paper repository records are only attributable to advice when the calling workflow includes an `advice_id`; unattributed records are safely ignored rather than guessed.
