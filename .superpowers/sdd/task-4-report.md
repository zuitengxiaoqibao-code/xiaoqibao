# Task 4 Implementation Report

Status: DONE

## Implemented

- Added a provider-agnostic OpenAI-compatible assessment explanation gateway configured by
  `QIBAO_AI_BASE_URL`, `QIBAO_AI_API_KEY`, and `QIBAO_AI_MODEL`.
- Added strict JSON response validation with forbidden extra fields and frozen evidence-ID scope.
- Added explicit `ready`, `unconfigured`, `timeout`, `http_error`, and `invalid` statuses.
- Preserved the deterministic assessment object for every gateway outcome. AI cannot change action,
  confidence, simulation eligibility, or authorized plan references.
- Added cockpit response fields `ai_status` and nullable `ai_explanation` while retaining historical
  cutoff behavior and request-local symbol evidence.
- Kept credentials private via `SecretStr`, private gateway storage, redacted `repr`, and responses
  that contain no provider error text or credential fields.
- Used dependency-injected `httpx.AsyncClient`; all provider tests use `httpx.MockTransport` and no
  external network request was sent.

## TDD Evidence

Initial focused run failed during collection because `qibao_api.a_shares.assessment_ai` did not
exist. After the minimal implementation, the focused gateway and cockpit suite passed 27 tests.
The broader lifespan run then exposed three missing-attribute failures in legacy `FakeSettings`;
the assembly code was made backward-compatible by treating absent AI fields as unconfigured.

## Verification

```powershell
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/test_settings.py apps/api/tests/routes/test_research.py apps/api/tests/libu_compliance/test_main_lifespan.py apps/api/tests/a_shares/test_assessment_ai.py apps/api/tests/a_shares/test_cockpit.py -q
```

Result: 59 passed.

```powershell
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests -q
```

Result: 565 passed.

```powershell
apps/api/.venv/Scripts/python.exe -m ruff check apps/api/src/qibao_api/a_shares/assessment_ai.py apps/api/src/qibao_api/a_shares/cockpit.py apps/api/src/qibao_api/settings.py apps/api/src/qibao_api/main.py apps/api/tests/a_shares/test_assessment_ai.py apps/api/tests/a_shares/test_cockpit.py
```

Result: all checks passed.

## Concerns

None within Task 4 scope. UI rendering and browser acceptance remain outside this task.

## Review Fixes

- Applied the gateway timeout explicitly to every HTTPX request, including when the caller injects
  a shared client. MockTransport verifies all four timeout extensions use the gateway value.
- Made owned HTTPX client creation lazy. An unconfigured gateway creates no client; a configured
  gateway closes only the client it created, while an injected lifespan client remains externally
  owned.
- Added frontend-only `AssessmentAIStatus` and `AssessmentAIExplanation` DTOs, separate from the
  decision workflow's AI status semantics.
- Added an assessment AI block directly inside the immediate-assessment section. It renders ready
  explanations, an explicit unconfigured state, and a common degraded state while keeping the
  deterministic conclusion visible.

Review RED evidence: backend tests failed because `client_factory` was unsupported and an injected
client retained its 5-second default instead of the configured 2.5 seconds. Five new frontend
assertions failed because no assessment AI status or explanation was rendered.

Review verification:

```powershell
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_assessment_ai.py apps/api/tests/a_shares/test_cockpit.py apps/api/tests/routes/test_research.py -q
pnpm --filter @qibao/web test -- StockDecisionCockpit.test.tsx
pnpm --filter @qibao/web build
```

Result: 54 backend tests passed; 16 frontend files and 116 tests passed; production build passed.
