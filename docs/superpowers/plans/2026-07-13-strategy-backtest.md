# 策略研究与回测实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地历史日线上运行可复现、计入成本且不泄漏未来数据的固定双均线策略回测。

**Architecture:** 中书省回测引擎只消费 `DailyBar`，收盘生成信号并在下一交易日开盘模拟成交。引擎输出交易、权益曲线、收益、最大回撤和样本分段结果；API 从 DuckDB 读取数据，前端以后复用相同结果契约。

**Tech Stack:** Python 3.12、Pydantic 2.11.7、Decimal、pytest、FastAPI。

## Global Constraints

- 不使用未来数据；信号与成交至少间隔一个交易日。
- 计入佣金和滑点；涨跌停无法成交时跳过。
- 第一版只有固定双均线模板，不执行 AI 生成代码。
- 回测结果不构成收益承诺。

---

### Task 1: 定义回测契约

**Files:**
- Create: `apps/api/src/qibao_api/contracts/backtest.py`
- Test: `apps/api/tests/contracts/test_backtest.py`

**Interfaces:** Produces `BacktestRequest`, `Trade`, `EquityPoint`, `BacktestResult`.

- [ ] Write a failing test requiring `fast_window < slow_window` and positive initial cash.
- [ ] Run focused test and confirm import failure.
- [ ] Implement Pydantic contracts with Decimal monetary fields and explicit strategy id `sma_cross`.
- [ ] Run GREEN and commit `feat: define reproducible backtest contracts`.

### Task 2: 实现双均线信号与次日成交

**Files:**
- Create: `apps/api/src/qibao_api/zhongshu/backtest.py`
- Test: `apps/api/tests/zhongshu/test_backtest.py`

**Interfaces:** Produces `BacktestEngine.run(request, bars) -> BacktestResult`.

- [ ] Write RED proving a cross on day N cannot trade before day N+1 open.
- [ ] Write RED proving commission and slippage reduce ending equity.
- [ ] Implement rolling-close signals, next-open execution, all-in integer shares and final mark-to-market.
- [ ] Add RED/GREEN for limit-up buy and limit-down sell rejection using 9.8% threshold.
- [ ] Run full focused suite and commit `feat: add cost-aware SMA backtest engine`.

### Task 3: 增加绩效指标与样本分段

**Files:**
- Create: `apps/api/src/qibao_api/zhongshu/performance.py`
- Test: `apps/api/tests/zhongshu/test_performance.py`

**Interfaces:** Produces `max_drawdown(points)`, `split_bars(bars, train_ratio, validation_ratio)`.

- [ ] Write RED for a known 100→120→90 curve producing 25% drawdown.
- [ ] Write RED proving train/validation/out-of-sample sets are chronological and non-overlapping.
- [ ] Implement Decimal metrics and deterministic index boundaries.
- [ ] Run GREEN and commit `feat: add backtest performance attribution`.

### Task 4: 暴露回测 API

**Files:**
- Create: `apps/api/src/qibao_api/routes/backtest.py`
- Modify: `apps/api/src/qibao_api/main.py`
- Test: `apps/api/tests/routes/test_backtest.py`

**Interfaces:** Produces `POST /api/v1/a-shares/{symbol}/backtests`.

- [ ] Write RED: missing local history returns 409 with a sync-first explanation.
- [ ] Write RED: valid history returns result with trades, costs and max drawdown.
- [ ] Implement route using `market_data_service.repository.latest`, sorting bars ascending before engine execution.
- [ ] Run backend tests, Ruff and live request for `600000`; commit `feat: expose fixed-strategy backtest API`.
