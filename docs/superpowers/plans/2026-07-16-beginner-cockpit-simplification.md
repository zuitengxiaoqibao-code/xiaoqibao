# Beginner Cockpit Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the paper-trading product surface, automatically prepare real A-share evidence, and replace the department-oriented dashboard with a beginner action cockpit.

**Architecture:** Keep deterministic assessment authoritative. Add one idempotent preparation service that reports source-level progress and refreshes stored evidence, one local AI configuration repository that never returns secrets, and a simplified web shell that presents action, reasons, risks, and three-phase history. Convertible bonds stay on an isolated route and state domain.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, DuckDB/SQLite, httpx, React 19, TypeScript 5.8, Vite 7, Vitest, Testing Library.

## Global Constraints

- Do not connect to a broker or create any real or simulated order.
- Remove paper accounts, cash, positions, orders, fills, and paper-trading runtime services.
- Action values are exactly `wait`, `observe`, and `avoid`; visible labels are `暂不参与`, `加入观察`, and `回避`.
- AI may explain evidence but may not change action, confidence, numbers, or risk gates.
- Do not invent fund-flow data; remove `funds` from the core/default experience until a real source is integrated.
- Backtest is optional history content and is not a required stock-assessment section.
- Historical reads must preserve the request cutoff end to end.
- A-share and convertible-bond routes, selection state, and contracts remain isolated.
- AI secrets stay under `.runtime`, are ignored by Git, are never logged, and are never returned by an API.
- Chinese source files must be edited with `apply_patch`; run the project mojibake scan after changes.

---

### Task 1: Remove Paper Trading End To End

**Files:**
- Delete: `apps/web/src/features/paper-trading/`
- Delete: `apps/api/src/qibao_api/routes/paper.py`
- Delete: `apps/api/src/qibao_api/bingbu/paper_broker.py`
- Delete: `apps/api/src/qibao_api/bingbu/paper_service.py`
- Delete: `apps/api/src/qibao_api/bingbu/simulation_plan.py`
- Delete: `apps/api/src/qibao_api/hubu/repository.py`
- Delete: `apps/api/tests/routes/test_paper.py`
- Delete: `apps/api/tests/bingbu/test_paper_broker.py`
- Delete: `apps/api/tests/bingbu/test_paper_service.py`
- Delete: `apps/api/tests/bingbu/test_paper_concurrency.py`
- Modify: `apps/api/src/qibao_api/main.py`
- Modify: `apps/api/src/qibao_api/dependencies.py`
- Modify: `apps/api/src/qibao_api/shangshu/postclose_context.py`
- Modify: `apps/api/src/qibao_api/zhongshu/postclose_review.py`
- Modify: `apps/api/src/qibao_api/contracts/decision.py`
- Modify: `apps/api/src/qibao_api/shangshu/decision_repository.py`
- Modify: `apps/api/src/qibao_api/shangshu/intraday_monitor.py`
- Modify: `apps/api/src/qibao_api/routes/decisions.py`
- Modify: `apps/api/src/qibao_api/a_shares/assessment.py`
- Modify: `apps/api/src/qibao_api/a_shares/cockpit.py`
- Modify: `apps/web/src/app/App.tsx`
- Modify: `apps/web/src/features/dashboard/Dashboard.tsx`
- Test: `apps/api/tests/test_app.py`
- Test: `apps/web/src/features/dashboard/Dashboard.test.tsx`

**Interfaces:**
- Produces: application startup with no `paper_repository`, `paper_service`, simulation-plan builder, or `/api/v1/paper` routes.
- Produces: post-close context from decision/audit repositories only.
- Produces: decision snapshots containing advice and evidence but no simulated-plan action, plan IDs, prices, positions, stops, or plan collection.

- [ ] **Step 1: Write failing removal tests**

```python
def test_paper_routes_are_not_registered(client):
    response = client.get("/openapi.json")
    assert not any(path.startswith("/api/v1/paper") for path in response.json()["paths"])

def test_decision_responses_do_not_expose_simulation_plans(client):
    body = client.get("/api/v1/decisions/current").json()
    assert "plans" not in str(body)
    assert "simulation_plan_id" not in str(body)
```

```tsx
expect(screen.queryByText("模拟交易与资金台账")).not.toBeInTheDocument();
expect(screen.queryByText("模拟资金")).not.toBeInTheDocument();
```

- [ ] **Step 2: Run tests and verify RED**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/test_app.py apps/api/tests/routes/test_paper.py -q`

Run: `pnpm --filter @qibao/web test -- Dashboard.test.tsx`

Expected: paper route and visible paper panel assertions fail.

- [ ] **Step 3: Remove runtime and UI dependencies**

Remove paper imports, router registration, lifespan initialization, close calls, Dashboard props, App API wiring, and the paper panel. Refactor post-close constructors so their signatures no longer accept `PaperRepository`; derive observed outcomes from `DecisionRepository` and audit evidence only.

Remove `SimulationPlan`, `SimulationPlanBuilder`, `simulated_plan`, `simulation_plan_id`, snapshot plan collections, plan persistence tables/queries, and plan serialization. Intraday evaluation may only emit `observe`, `wait`, or `avoid`, with evidence and invalidation conditions. Existing SQLite plan rows remain untouched on disk but are never read or written by the new runtime.

- [ ] **Step 4: Run focused and broad tests**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/test_app.py apps/api/tests/zhongshu apps/api/tests/shangshu -q`

Run: `pnpm --filter @qibao/web test`

Expected: PASS and no paper feature imports remain under `apps/web/src` or `apps/api/src/qibao_api`.

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "refactor: remove paper trading product"
```

### Task 2: Add Idempotent A-Share Data Preparation

**Files:**
- Create: `apps/api/src/qibao_api/a_shares/preparation.py`
- Modify: `apps/api/src/qibao_api/a_shares/cockpit.py`
- Modify: `apps/api/src/qibao_api/routes/research.py`
- Modify: `apps/api/src/qibao_api/main.py`
- Test: `apps/api/tests/a_shares/test_preparation.py`
- Test: `apps/api/tests/routes/test_research.py`

**Interfaces:**
- Produces: `PreparationSource(name, status, observed_at, reason)`.
- Produces: `StockPreparation(symbol, status, sources, refreshed, started_at, completed_at)`.
- Produces: `POST /api/v1/a-shares/{symbol}/prepare?as_of=YYYY-MM-DD`.
- Consumes: `MarketDataService.sync(symbol)`, diagnosis quote/finance sources, and `NewsIngestionService.collect()`.

- [ ] **Step 1: Write failing service tests**

```python
def test_prepare_syncs_missing_history_then_reassesses():
    result = service.prepare("600519", as_of=date(2026, 7, 16))
    assert history.sync_calls == ["600519"]
    assert result.status in {"ready", "partial"}
    assert {item.name for item in result.sources} >= {"quote", "history", "finance", "news"}

def test_prepare_is_idempotent_for_same_evidence_version():
    service.prepare("600519", as_of=date(2026, 7, 16))
    second = service.prepare("600519", as_of=date(2026, 7, 16))
    assert history.sync_calls == ["600519"]
    assert second.refreshed is False
```

- [ ] **Step 2: Verify RED**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_preparation.py -q`

Expected: FAIL because `AStockPreparationService` does not exist.

- [ ] **Step 3: Implement bounded preparation**

Implement a per-symbol lock and a stored freshness key. History sync runs only when fewer than 60 bars exist or the latest trading day is missing. Quote and finance checks reuse diagnosis adapters. News collection is bounded by the existing client timeout and stores only normalized events. Every source failure becomes a `partial` source result and never fabricates evidence.

The historical path passes `cutoff` to every read and never performs a live sync that could alter the requested historical evidence set.

- [ ] **Step 4: Add route and cockpit preparation state**

The prepare route returns 404 for an unverified symbol and a typed preparation result otherwise. Add `preparation` to `StockCockpitSnapshot`; remove hard-coded `funds` and `backtest` sections from `SECTION_NAMES` and assessment missing-section counts.

- [ ] **Step 5: Run tests and commit**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares apps/api/tests/routes/test_research.py -q`

```powershell
git add apps/api
git commit -m "feat: prepare A-share evidence on demand"
```

### Task 3: Add Safe Local AI Settings

**Files:**
- Create: `apps/api/src/qibao_api/settings_repository.py`
- Create: `apps/api/src/qibao_api/routes/settings.py`
- Modify: `apps/api/src/qibao_api/a_shares/assessment_ai.py`
- Modify: `apps/api/src/qibao_api/main.py`
- Modify: `apps/api/src/qibao_api/settings.py`
- Test: `apps/api/tests/test_settings_repository.py`
- Test: `apps/api/tests/routes/test_settings.py`

**Interfaces:**
- Produces: `GET /api/v1/settings/ai` returning `{configured, base_url, model, api_key_hint}`.
- Produces: `PUT /api/v1/settings/ai` accepting `{base_url, model, api_key}`.
- Produces: `DELETE /api/v1/settings/ai` clearing local configuration.
- Produces: a reloadable assessment gateway that reads the current local configuration for each explanation request.

- [ ] **Step 1: Write failing secret-boundary tests**

```python
def test_ai_settings_never_return_secret(client):
    client.put("/api/v1/settings/ai", json={
        "base_url": "https://api.example/v1", "model": "model-a", "api_key": "secret-value"
    })
    body = client.get("/api/v1/settings/ai").json()
    assert body["configured"] is True
    assert body["api_key_hint"].endswith("alue")
    assert "secret-value" not in str(body)
```

- [ ] **Step 2: Verify RED**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/test_settings_repository.py apps/api/tests/routes/test_settings.py -q`

- [ ] **Step 3: Implement repository and reloadable gateway**

Store `ai-settings.json` under `Settings.data_dir` using an atomic temporary-file replace. Reject non-HTTP(S) URLs, blank models, and blank secrets. Never log request bodies. Environment variables remain the initial fallback, but an explicitly saved local config takes precedence.

- [ ] **Step 4: Run security and gateway tests**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/test_settings.py apps/api/tests/test_settings_repository.py apps/api/tests/routes/test_settings.py apps/api/tests/a_shares/test_assessment_ai.py -q`

- [ ] **Step 5: Commit**

```powershell
git add apps/api
git commit -m "feat: configure assessment AI locally"
```

### Task 4: Replace Department Dashboard With Beginner Navigation

**Files:**
- Create: `apps/web/src/features/beginner-shell/BeginnerNavigation.tsx`
- Create: `apps/web/src/features/beginner-shell/BeginnerNavigation.test.tsx`
- Modify: `apps/web/src/features/dashboard/Dashboard.tsx`
- Modify: `apps/web/src/features/dashboard/Dashboard.test.tsx`
- Modify: `apps/web/src/features/stock-cockpit/StockDecisionCockpit.tsx`
- Modify: `apps/web/src/features/stock-cockpit/StockDecisionCockpit.test.tsx`
- Modify: `apps/web/src/features/stock-cockpit/types.ts`
- Modify: `apps/web/src/features/stock-cockpit/CockpitSections.tsx`
- Modify: `apps/web/src/features/stock-cockpit/PhaseTimeline.tsx`
- Modify: `apps/web/src/app/App.tsx`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- Produces visible routes: `dashboard`, `a-shares`, `news-intelligence`, `risk`, `history`, `settings`, and isolated `convertible-bonds`.
- Consumes `StockPreparation` from Task 2.

- [ ] **Step 1: Write failing navigation and action-card tests**

```tsx
expect(screen.getByRole("button", { name: "今日研判" })).toBeInTheDocument();
expect(screen.getByRole("button", { name: "数据设置" })).toBeInTheDocument();
expect(screen.queryByText("中书省")).not.toBeInTheDocument();
expect(screen.queryByText("东厂")).not.toBeInTheDocument();
```

```tsx
expect(screen.getByText("加入观察")).toBeInTheDocument();
expect(screen.getByText("需要等待的信号")).toBeInTheDocument();
expect(screen.queryByText("模拟操作计划")).not.toBeInTheDocument();
```

- [ ] **Step 2: Verify RED**

Run: `pnpm --filter @qibao/web test -- Dashboard.test.tsx StockDecisionCockpit.test.tsx BeginnerNavigation.test.tsx`

- [ ] **Step 3: Implement the simplified shell**

Replace the department list and department copy. Keep risk, compliance, audit, and operations as background capabilities reached through plain-language risk/data settings pages. Remove all `SimulationPlan`, simulation gate, candidate ledger, price zone, position, stop, and order UI from the cockpit.

Map actions exactly: `wait -> 暂不参与`, `observe -> 加入观察`, `avoid -> 回避`. The first viewport contains selector, preparation status, action, confidence, up to three reasons, up to three risks, waiting signals, and re-evaluation conditions.

- [ ] **Step 4: Collapse technical detail**

Default-hide raw section payloads, snapshot IDs, strategy versions, department names, and unavailable cards. Add one expandable `数据详情` region showing coverage, source, timestamp, stale state, and failure reason.

- [ ] **Step 5: Run frontend tests and commit**

Run: `pnpm --filter @qibao/web test`

Run: `pnpm --filter @qibao/web build`

```powershell
git add apps/web
git commit -m "feat: simplify the beginner research cockpit"
```

### Task 5: Add Data Settings And Automatic Refresh Flow

**Files:**
- Create: `apps/web/src/features/data-settings/types.ts`
- Create: `apps/web/src/features/data-settings/api.ts`
- Create: `apps/web/src/features/data-settings/DataSettingsView.tsx`
- Create: `apps/web/src/features/data-settings/DataSettingsView.test.tsx`
- Modify: `apps/web/src/features/stock-cockpit/api.ts`
- Modify: `apps/web/src/features/stock-cockpit/StockDecisionCockpit.tsx`
- Modify: `apps/web/src/features/dashboard/Dashboard.tsx`
- Modify: `apps/web/src/app/App.tsx`

**Interfaces:**
- Consumes Task 2 prepare endpoint and Task 3 AI settings endpoints.
- Produces masked AI settings UI and per-source sync status.

- [ ] **Step 1: Write failing interaction tests**

```tsx
expect(screen.getByText("正在补齐数据")).toBeInTheDocument();
await waitFor(() => expect(loadCockpit).toHaveBeenCalledTimes(2));
```

```tsx
expect(screen.queryByDisplayValue("secret-value")).not.toBeInTheDocument();
expect(screen.getByText("密钥已保存 ····alue")).toBeInTheDocument();
```

- [ ] **Step 2: Verify RED**

Run: `pnpm --filter @qibao/web test -- DataSettingsView.test.tsx StockDecisionCockpit.test.tsx`

- [ ] **Step 3: Implement preparation refresh**

On symbol/date context change: load cockpit, call prepare when live data is incomplete, show source progress, then reload cockpit once when `refreshed=true`. Abort stale symbol/date generations and never loop preparation requests.

- [ ] **Step 4: Implement settings UI**

Show source availability, last successful timestamp, failure reason, retry button, and automatic-sync toggle. Save AI settings through the API; never prefill or render the secret. Clearing the secret requires an explicit `清除 AI 配置` command.

- [ ] **Step 5: Run tests and commit**

Run: `pnpm --filter @qibao/web test`

Run: `pnpm --filter @qibao/web build`

```powershell
git add apps/web
git commit -m "feat: add beginner data settings"
```

### Task 6: Integration, Documentation, And Browser Acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`
- Test: `apps/api/tests/routes/test_research.py`
- Test: `apps/web/src/features/dashboard/Dashboard.test.tsx`

**Interfaces:**
- Verifies all prior task contracts together.

- [ ] **Step 1: Add integration regressions**

Cover one stock that prepares to `observe`, one insufficient stock that stays `wait`, and one adverse-event stock that becomes `avoid`. Assert no response or OpenAPI path exposes paper accounts, paper orders, simulation plans, or API secrets.

- [ ] **Step 2: Run complete verification**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests -q`

Run: `apps/api/.venv/Scripts/python.exe -m ruff check apps/api/src apps/api/tests scripts/restore_backup.py`

Run: `pnpm --filter @qibao/web test`

Run: `pnpm --filter @qibao/web build`

Run: `rg -n '�|锟|烫烫|\?\?\?' apps/api/src/qibao_api apps/api/tests apps/web/src README.md`

Run: `git diff --check`

- [ ] **Step 3: Browser acceptance**

At `1440x900` and `390x844`, verify all six beginner routes, stock switching, preparation progress, action labels, AI unconfigured/configured states, historical cutoff, convertible-bond isolation, no horizontal overflow, and no console warning/error.

- [ ] **Step 4: Update documentation and commit**

Document the removed paper product, real data-source priorities, action semantics, local AI settings, and known data-source limits.

```powershell
git add README.md docs apps/api/tests apps/web/src
git commit -m "docs: complete beginner cockpit delivery"
```
