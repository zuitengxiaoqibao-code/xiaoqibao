# Task 3 实施报告

## 状态

已完成任意 A 股即时研判前端接入。驾驶舱首屏始终展示后端 `assessment`，候选账本建议作为独立交易层展示。

## 实现

- 补齐 `StockAssessment` 与证据类型，接入 `StockCockpitSnapshot.assessment`。
- 非候选股票仍展示结论、置信度、支持/反方证据、风险与失效条件，并明确不生成模拟买卖方案。
- 候选账本建议与即时研判分层，四项 `simulation_gate` 状态逐项可见。
- 模拟方案必须同时满足后端 `assessment.simulation_eligible` 和账本引用完整性校验；前端不会重算并放宽后端资格。
- 新增 520px 移动布局，新增文字均不低于 11px。

## TDD 与验证

- RED：新增非候选即时研判、后端资格不可放宽、四项门禁测试，首次运行 3 项按预期失败。
- 聚焦测试：`pnpm --filter @qibao/web exec vitest run src/features/stock-cockpit/StockDecisionCockpit.test.tsx`，12/12 通过。
- 全前端测试：`pnpm --filter @qibao/web test`，16 个测试文件、110 个测试通过。
- 构建：`pnpm --filter @qibao/web build` 通过。
- 中文乱码扫描、`git diff --check` 通过。

## 关注点

无阻塞。门禁原始状态值沿用 API 枚举显示，避免前端二次解释改变权威含义。
