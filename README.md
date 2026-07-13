# 小七宝量化决策台

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

腾讯行情属于免费数据源，可能改变格式、限流或暂时不可用。系统会明确暴露错误，不会用虚构数据替代真实结果。
