# Task 2 实施报告

## 状态

已实现任意 A 股即时确定性研判，并接入驾驶舱快照。未实现 Task 3 UI 或 Task 4 AI，也未新增或写入三阶段决策账本。

## RED

命令：

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_assessment.py -q`

结果：退出码 1；测试收集因 `ModuleNotFoundError: No module named 'qibao_api.a_shares.assessment'` 失败，确认待实现模块不存在。

## GREEN

单元测试命令：

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_assessment.py -q`

结果：5 passed。

聚焦回归命令：

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_assessment.py apps/api/tests/a_shares/test_cockpit.py apps/api/tests/routes/test_research.py -q`

结果：40 passed。

静态检查命令：

`apps/api/.venv/Scripts/python.exe -m ruff check apps/api/src/qibao_api/a_shares/assessment.py apps/api/src/qibao_api/a_shares/cockpit.py apps/api/tests/a_shares/test_assessment.py apps/api/tests/a_shares/test_cockpit.py`

结果：All checks passed。

附加检查：乱码模式扫描无命中；`git diff --check` 通过。

## 文件

- `apps/api/src/qibao_api/a_shares/assessment.py`
- `apps/api/src/qibao_api/a_shares/cockpit.py`
- `apps/api/tests/a_shares/test_assessment.py`
- `apps/api/tests/a_shares/test_cockpit.py`

## 契约与规则

- 冻结 `StockAssessment` 契约，动作限制为 `observe`、`wait`、`avoid`。
- 固定优先级为风险阻断 `avoid`，再到行情或日线不足 `wait`，最后为 `observe`。
- 证据 ID 对分区、来源、观察时间、状态、原因和指标做确定性 SHA-256 哈希。
- 非候选的 `simulation_eligible` 固定为 `false`；候选也必须是 `observe` 才为 `true`。
- `generated_at` 使用驾驶舱有效 cutoff，证据不会晚于 cutoff。

## Commit

本报告随 `feat(research): add deterministic stock assessment` 提交（当前提交 `HEAD`）。

## 自审与 Concerns

自审未发现越过 Task 2 边界的实现。聚焦测试首次运行时有一个既有 FastAPI lifespan/DuckDB 中文路径解码失败；该用例单独复跑通过，随后完整聚焦集合也通过，未修改该无关路径。其余无已知 concern。
