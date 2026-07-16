# Task 2 实施报告

## 状态

已实现任意 A 股即时确定性研判，并接入驾驶舱快照。未实现 Task 3 UI 或 Task 4 AI，也未新增或写入三阶段决策账本。

## RED

命令：

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_assessment.py -q`

结果：退出码 1；测试收集因 `ModuleNotFoundError: No module named 'qibao_api.a_shares.assessment'` 失败，确认待实现模块不存在。

Review 修复 RED 命令：

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_assessment.py apps/api/tests/a_shares/test_cockpit.py -q`

结果：18 failed、4 passed。失败准确覆盖候选身份错误提升模拟资格、缺失观察时间伪造成证据、缺少四门禁派生、缺少历史/实时完成边界。

## GREEN

单元测试命令：

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_assessment.py -q`

结果：5 passed。

聚焦回归命令：

`apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_assessment.py apps/api/tests/a_shares/test_cockpit.py apps/api/tests/routes/test_research.py -q`

结果：48 passed。

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
- 证据 ID 对分区、来源、真实观察时间、状态、原因和指标做确定性 SHA-256 哈希。
- 没有真实 `observed_at` 或持久 `snapshot_id` 的分区不生成 `EvidenceReference`，仅形成明确缺失风险；不伪造 cutoff 或 source snapshot 身份。
- assessor 对 `simulation_eligible` 保守默认 `false`。驾驶舱仅从当前 `simulated_plan` 建议中派生资格，并要求 plan/risk ID 互证及 quote/compliance/evidence/risk 四门禁全部通过。
- 历史请求严格保持调用 cutoff。实时请求使用真实完成时钟作为返回 cutoff，并把晚于完成时间的分区降级为不可用；assessment 只消费不晚于返回 cutoff 的分区。

## Commit

初始实现为 `5dd598e`。Review P1 修复随 `fix(research): enforce assessment evidence and gate boundaries` 提交。

## 自审与 Concerns

自审未发现越过 Task 2 边界的实现。没有写三阶段账本、Task 3 UI 或 Task 4 AI。聚焦测试首次运行时有一个既有 FastAPI lifespan/DuckDB 中文路径解码失败；该用例单独复跑通过，随后完整聚焦集合也通过，未修改该无关路径。其余无已知 concern。
