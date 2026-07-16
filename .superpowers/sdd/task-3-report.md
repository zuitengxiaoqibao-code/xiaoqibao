# Task 3 实施报告

## 状态

已完成任意 A 股即时研判前端接入。驾驶舱首屏始终展示后端 `assessment`，候选账本建议作为独立交易层展示。

## 实现

- 补齐 `StockAssessment` 与证据类型，接入 `StockCockpitSnapshot.assessment`。
- 非候选股票仍展示结论、置信度、支持/反方证据、风险与失效条件，并明确不生成模拟买卖方案。
- 候选账本建议与即时研判分层，四项 `simulation_gate` 状态逐项可见。
- 后端仅从同一聚合内真实 plan、双向引用、有效期与四项门禁均通过的当前建议中生成单一权威引用：`authorized_simulation_advice_id` + `authorized_simulation_plan_id`。
- 多条已授权建议按盘中优先、波段其次，同周期内最新优先选一条；未授权、伪造或过期方案不会返回引用。
- 前端删除本地 `planGateReady` 重算，只按权威 advice ID 定位建议并展示后端 plan ID；引用缺失或无法定位时明确不展示方案。
- 新增 520px 移动布局，新增文字均不低于 11px。

## TDD 与验证

- RED：新增非候选即时研判、四项门禁和权威方案身份测试；P1 修复中后端新增 3 项按预期失败，前端多 horizon 用例按预期失败。
- 后端聚焦测试：assessment、cockpit、routes 共 52/52 通过。
- 前端聚焦测试：`pnpm --filter @qibao/web exec vitest run src/features/stock-cockpit/StockDecisionCockpit.test.tsx`，13/13 通过。
- 全前端测试：`pnpm --filter @qibao/web test`，16 个测试文件、111 个测试通过。
- 构建：`pnpm --filter @qibao/web build` 通过。
- Ruff、中文乱码扫描、`git diff --check` 通过。

## 关注点

无阻塞。全前端首次运行出现一项既有情报流异步测试波动，完整复跑 111/111 通过；本任务聚焦测试两次均通过。
