# 可转债独立资产域实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Use checkbox steps and TDD.

**Goal:** 建立与 A 股隔离的可转债行情、指标、诊断、候选池和风险规则。

**Architecture:** 可转债实现统一资产域接口，但拥有独立数据模型、路由、页面和策略。只共享工部基础设施、账户、审计、AI 解释和通用风控；禁止复用 A 股专属评分。

## Tasks

### Task 1: 转债基础契约
- Define bond code, linked stock, conversion price, maturity, remaining size and clause dates.
- Validate bond codes independently from A-share routes.
- Tests prove `113001` is accepted by bond domain and rejected by A-share domain.

### Task 2: 行情和条款数据
- Add replaceable quote and clause adapters with source/time metadata.
- Store raw clause snapshots and normalized events; never overwrite earlier terms.
- Tests cover missing linked stock, suspended bond and changed conversion price.

### Task 3: 专属指标
- Calculate conversion value, conversion premium, pure-bond premium, remaining term and size.
- Decimal formula tests use published examples and round only at display boundary.
- Strong-redemption state must be evidence-backed, not inferred from name or price alone.

### Task 4: 转债风险与候选池
- Add liquidity, premium, remaining size, maturity and strong-redemption risk rules.
- Candidate list is independent from A-share rankings and has its own filters.
- Backtests include T+0 capability only when strategy explicitly enables it.

### Task 5: Independent UI
- Create `/convertible-bonds` navigation, dashboard, diagnosis and candidate pages.
- Show linked-stock context without embedding the bond in A-share tables.
- Tests cover empty clauses, stale quote, strong-redemption warning and source conflict.

## Acceptance

- No A-share factor is implicitly applied to a bond.
- Every premium value is reproducible from stored inputs.
- Strong-redemption warnings show clause evidence and data time.
- Future asset domains can be added without modifying bond internals.

