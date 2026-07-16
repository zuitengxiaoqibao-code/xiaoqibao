# 新闻有效事件视图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改写历史新闻事件的前提下，以幂等系统修正承接链接规则升级，并让所有研判链路读取修正后的有效事件。

**Architecture:** 原始事件和修正继续分别追加到 SQLite；仓储新增系统事件协调与有效事件投影视图。审计、备份和质量基数保留原始读取，诊断、准备、简报与决策切换到有效读取。

**Tech Stack:** Python 3.12、Pydantic 2、SQLite、FastAPI、pytest。

## Global Constraints

- 不更新、不删除或重建现有新闻事件和运行时数据库。
- 只有链接器派生字段允许系统修正；核心证据字段冲突必须继续失败。
- 自动修正不得计入人工修正率。
- AI 不参与修正，也不改变确定性行动。
- 中文文件只用 `apply_patch` 修改，完成后运行乱码扫描。

---

### Task 1: 修正契约与有效仓储视图

**Files:**
- Modify: `apps/api/src/qibao_api/contracts/news.py`
- Modify: `apps/api/src/qibao_api/gongbu/news_repository.py`
- Modify: `apps/api/tests/gongbu/test_news_repository.py`

**Interfaces:**
- Produces: `NewsCorrection.origin` and optional `association_confidence`
- Produces: `NewsRepository.reconcile_event(event) -> tuple[bool, bool]`
- Produces: `effective_events(cutoff=None)` and `effective_events_for_symbol(symbol, cutoff=None)`

- [ ] Write repository tests for immutable originals, system correction projection, idempotency, correction/event cutoff filtering and rejection of core evidence changes.
- [ ] Run the focused tests and confirm failures for the missing contract and methods.
- [ ] Implement the minimum compatible contract, deterministic correction ID, integrity validation and effective projections.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: 摄取和研判消费者接线

**Files:**
- Modify: `apps/api/src/qibao_api/gongbu/news_ingestion.py`
- Modify: `apps/api/src/qibao_api/a_shares/diagnosis.py`
- Modify: `apps/api/src/qibao_api/a_shares/preparation.py`
- Modify: `apps/api/src/qibao_api/shangshu/daily_briefing.py`
- Modify: `apps/api/src/qibao_api/shangshu/decision_runtime.py`
- Modify: `apps/api/src/qibao_api/zhongshu/premarket_decision.py`
- Modify: corresponding focused tests under `apps/api/tests/`

**Interfaces:**
- Consumes: `reconcile_event()` during ingestion.
- Consumes: effective event methods in all deterministic research consumers.

- [ ] Write ingestion and consumer tests proving taxonomy changes do not fail and stale labels are not consumed.
- [ ] Run the focused tests and confirm expected failures.
- [ ] Wire ingestion and all research consumers to the new repository boundary.
- [ ] Re-run the focused tests and confirm they pass.

### Task 3: 质量指标和生产验证

**Files:**
- Modify: `apps/api/src/qibao_api/zhongshu/news_quality.py`
- Modify: `apps/api/tests/zhongshu/test_news_quality.py`
- Modify only additional files required by verification findings.

**Interfaces:**
- Produces: human correction rate filtered by `origin=human`.

- [ ] Write and run the failing quality test for mixed human and system corrections.
- [ ] Implement origin-aware quality counting and run focused tests.
- [ ] Run all API tests, Ruff, web tests, production build, mojibake scan and `git diff --check`.
- [ ] Restart or reuse local services, prepare `600519`, verify news readiness and unchanged deterministic output, then inspect desktop and mobile layouts.
- [ ] Commit and push the verified batch to `codex/a-share-daily-research`.
