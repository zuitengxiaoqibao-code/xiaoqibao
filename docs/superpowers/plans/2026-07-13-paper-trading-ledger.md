# 模拟交易与资金账本实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Use checkbox steps and TDD.

**Goal:** 打通吏部资金预算、兵部模拟方案、户部委托成交和组合复盘。

**Architecture:** 所有模拟指令必须引用行情快照和刑部审查结果。SQLite 保存账户、委托、成交、持仓和现金流水；成交引擎按 A 股 100 股整数手、佣金、滑点、涨跌停和可用资金执行，不连接券商。

## Tasks

### Task 1: 账户与订单契约
- Create `contracts/trading.py`: `PaperAccount`, `Position`, `OrderRequest`, `Fill`, `LedgerEntry`.
- Validate six-digit A 股代码, 100-share lots, positive price, supported buy/sell sides.
- Tests reject oversize, odd-lot and negative-price orders.

### Task 2: 户部持久化账本
- Create `hubu/schema.py` and `hubu/repository.py` using SQLite transactions.
- Enforce idempotent client order ids and double-entry cash records.
- Tests prove restart recovery and rollback on partial failure.

### Task 3: 吏部资金与仓位预算
- Create `libu/allocation.py` with available cash, single-position cap and total exposure.
- Default caps: single position 20%, total exposure 80%; store settings per paper account.
- Tests cover insufficient cash and concentration rejection.

### Task 4: 兵部模拟成交
- Create `bingbu/paper_broker.py`; consume fresh quote snapshot, risk approval and order.
- Apply commission, slippage, limit-up buy rejection and limit-down sell rejection.
- Persist rejected orders with explicit reasons; never silently drop a command.

### Task 5: API and UI
- Add account, order, position and ledger endpoints under `/api/v1/paper`.
- Build 吏部/户部/兵部 views with cash, exposure, holdings, order ticket and audit trail.
- Browser states: empty account, loading, rejected, filled, insufficient funds and source unavailable.

## Acceptance

- Restart preserves account and ledger.
- Cash plus marked positions reconciles to total equity.
- Every fill references quote time, source, order id and risk decision.
- No real broker or credential integration exists.

