# 风控、合规与独立审计实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Use checkbox steps and TDD.

**Goal:** 建立刑部实时风控、东厂独立审计和礼部授权留痕。

**Architecture:** 刑部在模拟指令执行前同步判定，东厂异步检查数据冲突、模型漂移和结果偏差，礼部维护数据授权与风险声明。所有规则有版本号，历史决策按当时版本还原。

## Tasks

### Task 1: 规则和决策契约
- Define `RiskRule`, `RiskDecision`, `ComplianceRecord`, `AuditFinding`.
- Decision outcomes: approve, reduce, reject, observe-only.
- Tests require evidence, rule version, timestamp and machine-readable reason code.

### Task 2: 刑部实时规则
- Implement data freshness, max position, total exposure, industry concentration, liquidity and drawdown rules.
- Compose rules deterministically; reject overrides approve.
- Property tests cover boundary values and rule ordering independence.

### Task 3: 礼部合规登记
- Store source license/permission state, disclaimer version and user acknowledgement.
- Block features whose required source authorization is missing.
- Tests prove revoked permission disables new collection but preserves historical audit data.

### Task 4: 东厂事后审计
- Compare recommendation snapshot with later outcomes without rewriting the original conclusion.
- Detect duplicate news evidence, source conflicts, drift in signal frequency and abnormal rejection rates.
- Produce severity, evidence links, owner department and resolution state.

### Task 5: API and UI
- Add dedicated 刑部、东厂、礼部 pages; do not merge them into one generic risk page.
- Display current limits, recent rejections, audit findings, source permissions and rule versions.
- Tests cover empty findings, critical finding, stale policy and unavailable audit store.

## Acceptance

- Every simulated order has a persisted risk decision.
- Historical decisions remain reproducible after rule updates.
- Audit findings link to immutable input snapshots.
- Compliance state is visible and cannot be silently bypassed.

