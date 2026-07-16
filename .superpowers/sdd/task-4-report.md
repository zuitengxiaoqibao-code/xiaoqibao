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
