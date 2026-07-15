# 小七宝量化决策台

> 2026-07-15：根路由现为 A 股盘前、盘中、盘后三阶段决策工作台。浏览器只轮询聚合决策 API；模拟计划仅在确定性门禁状态及相互引用全部通过时展示；可转债继续使用独立路由。决策 SQLite 已纳入备份和仓储级哈希链恢复校验。V1 仍在实施，部门工作区、浏览器验收和最终生产审计尚未完成。

盘中接口同时返回跨盘前与盘中变化链物化的“当前观察状态”，以及独立版本化的本次变化流。轮询状态、失败次数、成功时间、下一次到期时间和 60/180-300 秒实际间隔均来自持久化轮询状态，不由页面推测。

面向个人研究的本地 A 股量化决策辅助软件。当前版本已经打通真实行情、数据时效检查、研究摘要、风控拦截、审计存储和情报中枢界面。

本项目不连接券商，不自动下单，不构成投资建议。可转债是独立资产域，目前只建立了隔离边界，尚未接入转债专属指标。

## 当前能力

- 工部通过可替换适配器读取腾讯 A 股行情。
- 尚书省按照固定流程调度行情、存储、研究和风控。
- 中书省只生成可解释的行情观察卡，不输出虚构买卖信号。
- 刑部重新检查行情时效，超过三分钟自动拦截。
- SQLite 保存每次行情快照，支持后续审计。
- A 股和可转债使用独立路由与资产域。
- React 情报中枢覆盖等待、加载、有效、拦截和错误状态。
- 工部可同步历史日线到 DuckDB，并按标的导出 Parquet；mootdx 不可用时明确回退百度。
- 中书省提供固定双均线回测，使用次日开盘成交并计入佣金、滑点和涨跌停约束。

完整 V1 路线图见 `docs/superpowers/plans/2026-07-13-v1-roadmap.md`。

## 环境要求

- Windows 10 或 Windows 11
- Python 3.12
- Node.js 22 或更新版本
- pnpm 10 或更新版本

## 安装

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"
pnpm.cmd install
```

如果 PowerShell 禁止执行 `npm.ps1`，请直接使用 `pnpm.cmd`，不要修改系统执行策略。

## 启动

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

浏览器访问 `http://127.0.0.1:5173`。默认代码为 `600000`，点击“调取行情”即可获取真实快照。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest .\apps\api\tests -v
pnpm.cmd --filter @qibao/web test
pnpm.cmd --filter @qibao/web build
```

## 本地调度与备份

工部运维中心位于 `http://127.0.0.1:5173/operations`。尚书省会在已确认交易日按北京时间 09:20、10:30、13:30、14:30、15:30 自动运行每日简报；失败任务最多尝试三次，重启后会补查最近七天到期但未完成的槽位。

备份会在单进程写入闸门内冻结当前运行时，分别生成 SQLite 在线快照、DuckDB checkpoint 和 Parquet 副本，并写入 SHA-256 清单与外部追加式注册表。当前部署必须保持单个 API 进程，不要使用多个 Uvicorn worker。

恢复必须在新目录进行，不能在线覆盖正在使用的 `.runtime`：

```powershell
..venv\Scripts\python.exe .\scripts\restore_backup.py `
  backup-20260714T133107Z-e1148658 `
  .\.runtime-restored
```

工具会先完成清单校验和关键仓储恢复演练，再原子发布目标目录。确认新目录可用后，可通过 `QIBAO_DATA_DIR` 指向该目录启动 API 进行人工验收。

腾讯行情属于免费数据源，可能改变格式、限流或暂时不可用。系统会明确暴露错误，不会用虚构数据替代真实结果。
