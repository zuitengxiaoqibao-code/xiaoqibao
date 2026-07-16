# A 股行业与板块归属 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为单股诊断增加可追溯的所属行业和板块标签，并与新闻事件标签严格分离。

**Architecture:** 新增独立的东方财富分类采集器和 SQLite 不可变快照仓储。准备服务低频刷新快照，诊断服务按 `as_of`/`cutoff` 读取本地证据，前端继续使用现有通用指标列表展示新字段。

**Tech Stack:** Python 3.12、Pydantic 2、httpx、SQLite、FastAPI、React 19、Vitest、pytest。

## Global Constraints

- 只支持六位 A 股代码，不接入期货、账户、订单、资金或券商执行。
- AI 不参与行业或板块标签生成，也不改变确定性行动。
- 上游失败、空响应或字段无效时不得写入快照或成功冷却标记。
- 中文文件只用 `apply_patch` 修改；完成后必须运行乱码扫描。
- 东方财富请求必须串行、低频、复用现有 HTTP 客户端。

---

### Task 1: 分类采集器与不可变仓储

**Files:**
- Create: `apps/api/src/qibao_api/gongbu/stock_classification.py`
- Create: `apps/api/tests/gongbu/test_stock_classification.py`

**Interfaces:**
- Produces: `EastmoneyStockClassificationSource.fetch(symbol) -> StockClassificationSnapshot`
- Produces: `StockClassificationRepository.append(snapshot)` and `latest(symbol, as_of, cutoff=None)`
- Produces: `StockClassificationService.sync_symbol(symbol)`

- [ ] **Step 1: Write failing tests** for valid parsing, request parameters, invalid/empty response rejection, stable semantic hash, append-only persistence, duplicate idempotency and cutoff reads.
- [ ] **Step 2: Run** `pytest tests/gongbu/test_stock_classification.py -q` and confirm failure because the module does not exist.
- [ ] **Step 3: Implement** frozen classification models, sequential two-endpoint source, semantic hash, raw combined snapshot, append-only SQLite repository and one-method sync service.
- [ ] **Step 4: Run** `pytest tests/gongbu/test_stock_classification.py -q` and confirm all tests pass.

### Task 2: 诊断与准备服务接线

**Files:**
- Modify: `apps/api/src/qibao_api/a_shares/diagnosis.py`
- Modify: `apps/api/src/qibao_api/a_shares/preparation.py`
- Modify: `apps/api/tests/a_shares/test_diagnosis.py`
- Modify: `apps/api/tests/a_shares/test_preparation_review.py`

**Interfaces:**
- Consumes: `StockClassificationRepository.latest(symbol, as_of, cutoff=None)`
- Consumes: `StockClassificationService.sync_symbol(symbol)`
- Produces: industry metrics `industry`, `board_tags`
- Produces: news metric `event_industries` with the frozen news source and timestamp

- [ ] **Step 1: Write failing diagnosis tests** proving structured industry and board tags remain separate from news event industries, each keeps its own source and timestamp, and all respect cutoff.
- [ ] **Step 2: Write failing preparation tests** proving 24-hour per-symbol cooldown, failure retry and independent lock behavior.
- [ ] **Step 3: Run focused tests** and confirm failures for the missing constructor dependencies and metrics.
- [ ] **Step 4: Implement** local snapshot reads, separated industry/news section construction, action-risk isolation for optional classification, and low-frequency preparation refresh without adding a new core preparation source.
- [ ] **Step 5: Run focused tests** and confirm all pass.

### Task 3: Production wiring and beginner labels

**Files:**
- Modify: `apps/api/src/qibao_api/main.py`
- Modify: `apps/api/tests/libu_compliance/test_main_lifespan.py`
- Modify: `apps/web/src/features/stock-cockpit/CockpitSections.tsx`
- Modify: `apps/web/src/features/stock-cockpit/StockDecisionCockpit.test.tsx`

**Interfaces:**
- Produces: application state repository/service with deterministic shutdown.
- Produces: Chinese labels “所属行业”“板块标签”“新闻事件行业标签” under their respective evidence sections.

- [ ] **Step 1: Write failing lifespan and UI label tests** for dependency injection, closure and beginner-facing names.
- [ ] **Step 2: Run focused tests** and confirm expected failures.
- [ ] **Step 3: Register** the Eastmoney classification source, repository, service and compliance source; close the repository in lifespan cleanup; add UI metric labels.
- [ ] **Step 4: Run focused tests** and confirm all pass.

### Task 4: Production verification

**Files:**
- Modify only files required by verification findings.

**Interfaces:**
- Consumes: production `/prepare` and `/cockpit` endpoints.
- Produces: verified local 600519 industry and board evidence without changing action.

- [ ] **Step 1: Run** API tests, Ruff, web tests, production build, mojibake scan and `git diff --check`.
- [ ] **Step 2: Restart** the API, prepare `600519`, and verify persisted source evidence, industry value, board labels and unchanged deterministic action.
- [ ] **Step 3: Browser-check** desktop and 390x844 layouts, console errors and horizontal overflow.
- [ ] **Step 4: Commit and push** the verified batch to `codex/a-share-daily-research` and leave both local servers running.
