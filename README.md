# 小七宝 A 股观察台

面向新手的本地 A 股研究工具。选择一只已验证股票后，系统检查并补齐可获得的真实数据，再给出可追溯的确定性行动。主界面只有今日研判、A 股观察、新闻热点、风险提醒、历史复盘和数据设置六个入口；可转债使用独立入口、路由和选择状态。

当前产品不保留纸面交易：没有模拟资金、模拟账户、模拟委托、模拟成交或模拟操作计划。历史数据库文件不会被主动删除，但新运行时不读取或写入这些旧表。本项目也不连接券商、不下单、不提供买卖价格、仓位或止损，不构成投资建议。

## 新手行动

- `wait` / 暂不参与：核心行情或趋势证据不足，等待数据或信号。
- `observe` / 加入观察：已达到最低研判要求，未发现确定性风险阻断。
- `avoid` / 回避：存在明确风险事件、异常指标或规则阻断。

行动卡展示结论、置信度、主要依据、主要风险、等待信号、重新判断条件、数据时间和来源覆盖。动作、数字和风险门禁由确定性程序产生；AI 只能解释冻结证据，不能修改结论或补造缺失数据。

## 数据补全

当前股票的实时研判会自动检查数据覆盖，缺失时显示来源级进度并触发幂等补全，完成后至多自动重新研判一次。历史复盘只使用截止时间内可见的数据，不会触发实时补全。

真实来源优先级如下：

- 实时行情与估值：腾讯行情。
- 日线与趋势：优先通达信 `mootdx`，不可用时回退百度 K 线。
- 基本面：通达信财务快照。
- 新闻与个股事件：已采集新闻和本地冻结事件仓储；只有已核验且关联标的的事件进入确定性依据。
- 热点与行业：已接入的公开热点、行业信息或规范化新闻标签。
- 风险：基于行情、日线、基本面和已核验事件的确定性规则。

本阶段不伪造资金流。资金流不是核心研判分区；回测也不是每只股票的必需数据，只在存在真实结果时用于历史研究。免费公开源可能限流、改版或暂时不可用，系统会保留上次成功快照并标记陈旧，或明确显示失败原因，不会用估算值冒充真实结果。可转债目前只完成资产隔离，尚未接入完整转债专属指标。

## 环境与启动

需要 Windows 10/11、Python 3.12、Node.js 22 或更新版本，以及 pnpm 10 或更新版本。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"
pnpm.cmd install
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

浏览器访问 `http://127.0.0.1:5173`。可按六位代码或已观察中文名称搜索；A 股选择写入 URL 并支持刷新、前进和后退恢复。进入可转债专区会移除 A 股 `symbol`。

## 本地 AI 设置

在“数据设置”中保存 OpenAI 兼容 API 地址、模型和密钥。密钥只写入被 Git 忽略的本地运行目录；读取接口只返回是否已配置及脱敏尾部，不返回、预填或记录完整密钥。清除配置需要显式操作。

也可使用环境变量提供配置：

```powershell
$env:QIBAO_AI_BASE_URL = "https://your-compatible-endpoint/v1"
$env:QIBAO_AI_API_KEY = "your-api-key"
$env:QIBAO_AI_MODEL = "your-model"
```

三项必须同时有效才会请求模型。未配置、超时、HTTP 错误、非法输出或证据引用越界都不会影响确定性行动。

## 验证

```powershell
apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -q
apps\api\.venv\Scripts\python.exe -m ruff check apps\api\src apps\api\tests scripts\restore_backup.py
pnpm.cmd --filter @qibao/web test
pnpm.cmd --filter @qibao/web build
```

## 调度与备份

后台仍保留数据采集、风险、合规、审计、调度和备份服务，但不再以部门名称作为用户导航。每日任务按已确认交易日运行；失败任务最多尝试三次，重启后补查最近七天到期但未完成的槽位。

备份会生成 SQLite 在线快照、DuckDB checkpoint、Parquet 副本和 SHA-256 清单。当前部署须保持单个 API 进程。恢复必须发布到新目录，不能覆盖正在使用的 `.runtime`：

```powershell
..venv\Scripts\python.exe .\scripts\restore_backup.py `
  backup-20260714T133107Z-e1148658 `
  .\.runtime-restored
```

当前交付边界和后续数据工作见 [路线图](docs/roadmap.md)。
