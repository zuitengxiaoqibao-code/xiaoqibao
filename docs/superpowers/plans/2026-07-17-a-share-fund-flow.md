# A 股真实资金流证据 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接入可审计的东方财富日级和分钟级资金流，并把资金方向作为新手单股研判的可选支持或反方证据。

**Architecture:** 新建独立资金流采集/快照/SQLite 仓储模块，准备流程低频刷新，诊断按历史截止时间读取。确定性评估只改变资金流证据归类和风险文案，不改变现有动作门禁；前端在现有数据详情中增加资金流分区。

**Tech Stack:** Python 3.12、Pydantic 2、httpx、SQLite、FastAPI、React 19、TypeScript 5、pytest、Vitest。

## Global Constraints

- A 股为主域；不接入期货、模拟资金、账户、订单、仓位或券商执行。
- 东方财富请求必须串行、复用客户端、相邻请求间隔至少 1 秒。
- 缺失数值不得转换为 0，失败响应不得写入快照或成功冷却标记。
- 资金流不单独改变确定性动作和置信度。
- 中文文件只用 `apply_patch` 修改，完成后运行乱码扫描。

---

### Task 1: 资金流采集与不可变仓储

**Files:**
- Create: `apps/api/src/qibao_api/gongbu/fund_flow.py`
- Create: `apps/api/tests/gongbu/test_fund_flow.py`

**Interfaces:**
- Produces: `FundFlowSnapshot`
- Produces: `EastmoneyFundFlowSource.fetch(symbol) -> FundFlowSnapshot`
- Produces: `FundFlowRepository.append(snapshot)`, `latest(symbol, as_of, cutoff=None)`, `verify_all()` and `close()`
- Produces: `FundFlowService.sync_symbol(symbol)`

- [ ] Write failing tests with frozen daily/minute JSON for valid aggregation, exact endpoint parameters, sequential rate limiting, retryable statuses, empty/invalid values, immutable persistence, tamper detection and cutoff reads.
- [ ] Run `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/gongbu/test_fund_flow.py -q` and confirm collection fails because `qibao_api.gongbu.fund_flow` does not exist.
- [ ] Implement the frozen models, two-endpoint source, semantic/content hashes, append-only SQLite repository and sync service without adding dependencies.
- [ ] Re-run the focused tests and confirm all pass.

### Task 2: 诊断、评估和准备接线

**Files:**
- Modify: `apps/api/src/qibao_api/a_shares/diagnosis.py`
- Modify: `apps/api/src/qibao_api/a_shares/assessment.py`
- Modify: `apps/api/src/qibao_api/a_shares/cockpit.py`
- Modify: `apps/api/src/qibao_api/a_shares/preparation.py`
- Modify: `apps/api/tests/a_shares/test_diagnosis.py`
- Modify: `apps/api/tests/a_shares/test_assessment.py`
- Modify: `apps/api/tests/a_shares/test_cockpit.py`
- Modify: `apps/api/tests/a_shares/test_preparation_review.py`

**Interfaces:**
- Consumes: `FundFlowRepository.latest(symbol, as_of, cutoff=None)`
- Consumes: `FundFlowService.sync_symbol(symbol)` under a 300-second per-symbol cooldown.
- Produces: diagnosis section `funds` with metrics `latest_trade_date`, `latest_main_net`, `latest_super_net`, `latest_large_net`, `main_net_5d`, `main_net_20d`, `intraday_main_net`, `flow_direction`, `daily_sample_count`, `intraday_sample_count`.

- [ ] Write failing diagnosis tests for ready/missing/cutoff snapshots and unchanged core risk count.
- [ ] Write failing assessment tests proving inflow is supporting, outflow is contrary with a risk message, and neither changes action/confidence.
- [ ] Write failing preparation tests for independent cooldown, failure retry and non-core status isolation.
- [ ] Run the focused tests and confirm failures for the missing constructor ports, section and refresh path.
- [ ] Wire repository reads, optional risk semantics, cockpit mapping and preparation refresh; run the focused tests until green.

### Task 3: 生命周期、合规和备份

**Files:**
- Modify: `apps/api/src/qibao_api/libu_compliance/guard.py`
- Modify: `apps/api/src/qibao_api/main.py`
- Modify: `apps/api/src/qibao_api/gongbu/backup_service.py`
- Modify: `apps/api/tests/libu_compliance/test_main_lifespan.py`
- Modify: `apps/api/tests/gongbu/test_backup_service.py`

**Interfaces:**
- Produces: compliance feature `stock_fund_flow` backed by source `eastmoney`.
- Produces: application state `fund_flow_repository` and `fund_flow_service`.
- Produces: backup restore verification for `fund-flow.sqlite3`.

- [ ] Write failing lifespan tests for authorization registration, dependency identity and repository closure.
- [ ] Write a failing backup test that rejects a tampered fund-flow database.
- [ ] Register the authorized source, repository, service and cleanup; extend repository-level backup verification.
- [ ] Run the focused lifecycle and backup tests until green.

### Task 4: 新手资金流分区

**Files:**
- Modify: `apps/web/src/features/stock-cockpit/CockpitSections.tsx`
- Modify: `apps/web/src/features/stock-cockpit/StockDecisionCockpit.test.tsx`

**Interfaces:**
- Produces: “资金流” data band with beginner labels and `eastmoney-fund-flow` source name.
- Formats all net-flow amounts in yuan as signed billions of yuan; missing values remain “未提供”.

- [ ] Write a failing component test for positive, negative and missing amounts, source, timestamp and evidence ID.
- [ ] Add the `funds` definition, metric labels and signed-money formatter using the existing data-band layout.
- [ ] Run `pnpm --filter @qibao/web test -- StockDecisionCockpit.test.tsx` until green.

### Task 5: 生产验证

**Files:**
- Modify only files required by verification findings.

**Interfaces:**
- Produces: real `600519` fund-flow snapshot or an explicit verified upstream-unavailable state.

- [ ] Run all API tests, Ruff, web tests, production build, mojibake scan and `git diff --check`.
- [ ] Restart the API, prepare `600519`, verify source time/sample counts and unchanged deterministic action/confidence.
- [ ] Browser-check desktop and 390x844 layouts, console errors and horizontal overflow.
- [ ] Commit and push the verified batch to `codex/a-share-daily-research`, preserving both local services and the existing PR.
