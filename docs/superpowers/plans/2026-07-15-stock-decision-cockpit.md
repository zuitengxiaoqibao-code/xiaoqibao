# 单股决策驾驶舱实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在首页提供候选池与股票搜索，并让全局当前 A 股驱动完整的行情、诊断、新闻、风险、回测和三阶段决策详情。

**Architecture:** 后端新增 A 股标的目录与只读聚合服务，所有分区围绕服务器截止时间组合现有确定性服务和不可变决策账本。前端以 URL `symbol` 参数作为全局标的事实来源，通过独立 Provider 在首页、A 股研究及后续深链间共享选择，不把 A 股状态与可转债混用。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLite/DuckDB、React 19、TypeScript、Vitest、Lucide React。

## Global Constraints

- A 股是默认主域；可转债保持独立入口、搜索、状态和数据模型，不支持期货。
- 不连接真实券商，不自动下单；自选股仅保存本地观察标的。
- AI 只解释；价格、评分、建议动作、门禁和风险参数只由确定性程序产生。
- 缺失、陈旧、阻断和不可验证数据必须显示原因，不能用空白或虚构值代替。
- 所有分区返回来源、观察时间、快照版本和质量状态，并满足 `observed_at <= cutoff`。
- URL `?symbol=600000` 是全局 A 股选择的刷新恢复和浏览器历史事实来源。
- 正文和辅助文字不低于 `11px`；重要说明不低于 `12px`；手机端不得横向溢出。
- 中文文件只用 `apply_patch` 手工修改，完成后执行乱码扫描。

---

### Task 1: A 股标的目录与搜索接口

**Files:**
- Create: `apps/api/src/qibao_api/a_shares/instrument_directory.py`
- Create: `apps/api/tests/a_shares/test_instrument_directory.py`
- Modify: `apps/api/src/qibao_api/routes/research.py`
- Modify: `apps/api/tests/routes/test_research.py`
- Modify: `apps/api/src/qibao_api/main.py`

**Interfaces:**
- Produces: `AShareInstrument`, `AShareInstrumentDirectory.observe(...)`, `search(query, limit)`, `resolve(symbol)`。
- Produces: `GET /api/v1/a-shares/search?q={code_or_name}&limit=10`。
- Consumes later: Task 2 用 `resolve(symbol)` 提供标的身份；Task 3 用搜索接口提供选择结果。

- [ ] **Step 1: 写目录失败测试，固定 A 股隔离、排序和已观察名称**

```python
def test_search_prioritizes_exact_code_then_name_prefix(tmp_path: Path) -> None:
    directory = AShareInstrumentDirectory(tmp_path / "instruments.sqlite3")
    directory.observe(AShareInstrument(
        symbol="600000", name="浦发银行", exchange="sh",
        observed_at=NOW, quote_quality="ready",
    ))
    directory.observe(AShareInstrument(
        symbol="000001", name="平安银行", exchange="sz",
        observed_at=NOW, quote_quality="ready",
    ))
    assert [item.symbol for item in directory.search("600000", 10)] == ["600000"]
    assert [item.symbol for item in directory.search("平安", 10)] == ["000001"]

def test_directory_rejects_convertible_bond_and_index_codes(tmp_path: Path) -> None:
    directory = AShareInstrumentDirectory(tmp_path / "instruments.sqlite3")
    with pytest.raises(ValueError, match="A-share"):
        directory.observe(instrument(symbol="113065"))
```

- [ ] **Step 2: 运行目录测试并确认模块不存在**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/a_shares/test_instrument_directory.py -q`

Expected: FAIL，错误指向 `qibao_api.a_shares.instrument_directory` 不存在。

- [ ] **Step 3: 实现本地目录和确定性搜索排序**

```python
class AShareInstrument(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: AShareCode
    name: str = Field(min_length=1)
    exchange: Literal["sh", "sz", "bj"]
    observed_at: AwareDatetime
    quote_quality: Literal["ready", "stale", "unavailable"]

class AShareInstrumentDirectory:
    def search(self, query: str, limit: int = 10) -> tuple[AShareInstrument, ...]:
        normalized = query.strip().casefold()
        rows = self._all_rows()
        matches = [item for item in rows if normalized in item.symbol or normalized in item.name.casefold()]
        return tuple(sorted(matches, key=lambda item: (
            item.symbol != normalized,
            not item.name.casefold().startswith(normalized),
            item.symbol,
        ))[:limit])
```

目录使用 SQLite 追加观察记录并按股票代码读取最新版本；相同代码的新名称/质量生成新观察，不删除历史。启动时从本地 BarRepository 股票代码和已成功腾讯行情中补充目录。精确代码未在目录中时，路由调用现有腾讯 A 股行情源验证并写入目录；名称搜索只返回已观察名称，不猜测。

- [ ] **Step 4: 写搜索路由失败测试**

```python
def test_search_returns_only_a_shares_in_rank_order(client) -> None:
    response = client.get("/api/v1/a-shares/search?q=银行&limit=10")
    assert response.status_code == 200
    assert [item["symbol"] for item in response.json()["items"]] == ["000001", "600000"]
    assert all(item["asset"] == "a_share" for item in response.json()["items"])

def test_search_returns_empty_items_without_guessing(client) -> None:
    response = client.get("/api/v1/a-shares/search?q=不存在名称")
    assert response.status_code == 200
    assert response.json()["items"] == []
```

- [ ] **Step 5: 接入依赖、生命周期和路由**

`main.py` 创建单例目录并在关闭阶段释放连接；`research.py` 校验 `q` 非空、`limit` 在 `1..20`，返回 `query`、`items`、`server_time`。外部精确代码验证失败返回空结果和 `source_status="unavailable"`，不返回 500。

- [ ] **Step 6: 运行任务测试并提交**

Run:

```powershell
.venv\Scripts\python.exe -m pytest apps/api/tests/a_shares/test_instrument_directory.py apps/api/tests/routes/test_research.py -q
.venv\Scripts\ruff.exe check apps/api/src/qibao_api/a_shares apps/api/src/qibao_api/routes/research.py apps/api/tests/a_shares apps/api/tests/routes/test_research.py
```

Expected: PASS。

```powershell
git add apps/api/src/qibao_api/a_shares/instrument_directory.py apps/api/src/qibao_api/routes/research.py apps/api/src/qibao_api/main.py apps/api/tests
git commit -m "feat(research): add A-share instrument search"
```

---

### Task 2: 单股驾驶舱聚合服务与 API

**Files:**
- Create: `apps/api/src/qibao_api/a_shares/cockpit.py`
- Create: `apps/api/tests/a_shares/test_cockpit.py`
- Modify: `apps/api/src/qibao_api/routes/research.py`
- Modify: `apps/api/tests/routes/test_research.py`
- Modify: `apps/api/src/qibao_api/dependencies.py`
- Modify: `apps/api/src/qibao_api/main.py`

**Interfaces:**
- Consumes: `AShareInstrumentDirectory.resolve(symbol)`、`AShareDiagnosisService.diagnose(symbol, as_of)`、`DecisionRepository.cycles(...)`、新闻仓储和 BarRepository。
- Produces: `StockDecisionCockpitService.get(symbol, as_of, cutoff) -> StockCockpitSnapshot`。
- Produces: `GET /api/v1/a-shares/{symbol}/cockpit?as_of={date}`。

- [ ] **Step 1: 写聚合失败测试，固定截止时间和股票过滤**

```python
def test_cockpit_filters_every_phase_and_evidence_to_selected_symbol() -> None:
    result = service().get("600000", TRADE_DATE, CUTOFF)
    assert result.instrument.symbol == "600000"
    assert all(item.symbol == "600000" for phase in result.phases.values() for item in phase.advice)
    assert all(item.observed_at <= CUTOFF for item in result.all_evidence())
    assert result.phases["intraday"].change_stream[0].sequence == 1

def test_cockpit_degrades_only_failed_section() -> None:
    result = service(diagnosis=UnavailableValuation()).get("600000", TRADE_DATE, CUTOFF)
    assert result.sections["valuation"].status == "unavailable"
    assert result.sections["market"].status == "ready"
    assert result.overall_quality == "partial"
```

- [ ] **Step 2: 运行测试并确认聚合模块不存在**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/a_shares/test_cockpit.py -q`

Expected: FAIL，错误指向 `qibao_api.a_shares.cockpit` 不存在。

- [ ] **Step 3: 定义冻结响应契约**

```python
class CockpitSection(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["ready", "partial", "stale", "unavailable", "blocked"]
    source: str
    observed_at: AwareDatetime | None
    snapshot_id: str | None
    reason: str | None = None
    payload: dict[str, Any]

class StockCockpitSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: AShareCode
    as_of: date
    cutoff: AwareDatetime
    overall_quality: Literal["ready", "partial", "blocked"]
    instrument: AShareInstrument
    candidate_membership: tuple[Literal["short_term", "swing"], ...]
    current_advice: tuple[AdviceCard, ...]
    sections: dict[str, CockpitSection]
    phases: dict[DecisionPhase, StockPhaseHistory]
```

`sections` 固定包含 `market`、`price_volume`、`trend`、`valuation`、`fundamentals`、`funds`、`news`、`industry`、`risk`、`backtest`。未接入资金数据返回 `status="unavailable"`、`reason="fund_data_not_connected"`、空 payload。现有回测引擎没有持久化结果仓储；在用户尚未为该股票运行回测时，回测分区明确返回 `status="unavailable"`、`reason="backtest_not_run"`，不得临时选择策略参数自动运行。

- [ ] **Step 4: 实现同截止时间聚合和分区降级**

聚合服务调用现有服务时传入同一 `as_of/cutoff`；从三阶段账本中过滤 `advice.symbol == symbol`，变化流保留完整版本但只含该股票变化。当前建议按 `(horizon, created_at)` 取最新有效记录。每个分区单独捕获已知数据不可用异常并产生明确 reason；`DecisionIntegrityError` 不得降级吞掉，必须继续抛出。

- [ ] **Step 5: 写路由错误映射测试并实现 API**

```python
def test_cockpit_maps_invalid_and_unknown_symbol() -> None:
    assert client.get("/api/v1/a-shares/123/cockpit").status_code == 422
    assert client.get("/api/v1/a-shares/600999/cockpit").status_code == 404

def test_cockpit_hides_corrupt_decision_payload() -> None:
    response = corrupt_client.get("/api/v1/a-shares/600000/cockpit")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "decision_integrity_error"
    assert "advice" not in response.text
```

路由截止时间使用服务器北京时间；未来 `as_of` 返回 `422`。正常部分降级仍返回 `200`。

- [ ] **Step 6: 运行任务测试并提交**

Run:

```powershell
.venv\Scripts\python.exe -m pytest apps/api/tests/a_shares/test_cockpit.py apps/api/tests/routes/test_research.py -q
.venv\Scripts\ruff.exe check apps/api/src apps/api/tests
```

Expected: PASS。

```powershell
git add apps/api/src/qibao_api/a_shares/cockpit.py apps/api/src/qibao_api/routes/research.py apps/api/src/qibao_api/dependencies.py apps/api/src/qibao_api/main.py apps/api/tests
git commit -m "feat(research): aggregate stock decision cockpit"
```

---

### Task 3: 全局当前标的与候选/搜索选择器

**Files:**
- Create: `apps/web/src/features/instrument-selection/SelectedInstrumentProvider.tsx`
- Create: `apps/web/src/features/instrument-selection/SelectedInstrumentProvider.test.tsx`
- Create: `apps/web/src/features/stock-cockpit/api.ts`
- Create: `apps/web/src/features/stock-cockpit/types.ts`
- Create: `apps/web/src/features/stock-cockpit/StockSelector.tsx`
- Create: `apps/web/src/features/stock-cockpit/StockSelector.test.tsx`
- Modify: `apps/web/src/app/App.tsx`
- Modify: `apps/web/src/features/dashboard/Dashboard.tsx`

**Interfaces:**
- Produces: `useSelectedInstrument()`，包含 `symbol`、`source`、`select(symbol, source)`、`clear()`。
- Consumes: Task 1 搜索接口、现有候选接口。
- Produces later: Task 4 从 Provider 读取当前股票并加载驾驶舱。

- [ ] **Step 1: 写 URL 恢复和浏览器历史失败测试**

```tsx
it("restores the selected A-share from the symbol query parameter", () => {
  window.history.replaceState({}, "", "/?symbol=600000");
  render(<SelectedInstrumentProvider><Probe /></SelectedInstrumentProvider>);
  expect(screen.getByText("600000")).toBeInTheDocument();
});

it("writes each explicit selection to browser history", async () => {
  render(<SelectedInstrumentProvider><Probe /></SelectedInstrumentProvider>);
  await user.click(screen.getByRole("button", { name: "选择 000001" }));
  expect(new URL(window.location.href).searchParams.get("symbol")).toBe("000001");
});
```

- [ ] **Step 2: 实现 A 股专属 Provider**

Provider 只接受通过六位 A 股代码校验的 symbol。监听 `popstate` 恢复前进/后退选择；`select` 使用 `history.pushState`。不得读取或写入可转债路由状态。

- [ ] **Step 3: 写选择器失败测试**

```tsx
it("offers candidates and searches by code or name", async () => {
  render(<StockSelector loadCandidates={candidates} search={search} />);
  expect(await screen.findByRole("button", { name: /600000/ })).toBeInTheDocument();
  await user.type(screen.getByRole("searchbox", { name: "搜索 A 股" }), "平安");
  expect(await screen.findByRole("option", { name: /000001.*平安银行/ })).toBeInTheDocument();
});

it("does not replace an explicit selection when candidates poll", async () => {
  const view = render(<StockSelector loadCandidates={first} search={search} />);
  await user.click(await screen.findByRole("button", { name: /000001/ }));
  view.rerender(<StockSelector loadCandidates={second} search={search} />);
  expect(screen.getByRole("button", { name: /000001/ })).toHaveAttribute("aria-pressed", "true");
});
```

- [ ] **Step 4: 实现候选、搜索和本地自选标签**

搜索输入防抖 `250ms`，长度为 0 时关闭结果；六位代码可立即搜索。候选行显示名称、代码、涨跌幅、候选分、主要因子和观察时间。自选股使用独立 localStorage key `qibao.a_share.watchlist.v1`，只保存代码数组；显示数据仍从 API 获取。

- [ ] **Step 5: 接入 App 和首页，保留当前三阶段工作台**

`App.tsx` 在 A 股应用范围外层挂 Provider；`Dashboard` 组合 `StockSelector` 和现有 `DecisionWorkbench`，选择变化不卸载侧栏导航。若无候选且 URL 无 symbol，显示未选择说明，不自动猜测股票。

- [ ] **Step 6: 运行任务测试并提交**

Run:

```powershell
pnpm --filter @qibao/web test -- SelectedInstrumentProvider.test.tsx StockSelector.test.tsx Dashboard.test.tsx
pnpm --filter @qibao/web build
```

Expected: PASS。

```powershell
git add apps/web/src/features/instrument-selection apps/web/src/features/stock-cockpit apps/web/src/app/App.tsx apps/web/src/features/dashboard
git commit -m "feat(web): add global A-share selection"
```

---

### Task 4: 结论优先、数据完整的驾驶舱界面

**Files:**
- Create: `apps/web/src/features/stock-cockpit/StockDecisionCockpit.tsx`
- Create: `apps/web/src/features/stock-cockpit/StockDecisionCockpit.test.tsx`
- Create: `apps/web/src/features/stock-cockpit/CockpitSections.tsx`
- Create: `apps/web/src/features/stock-cockpit/PhaseTimeline.tsx`
- Modify: `apps/web/src/features/dashboard/Dashboard.tsx`
- Modify: `apps/web/src/features/decision-workbench/DecisionWorkbench.tsx`
- Modify: `apps/web/src/app/theme.css`

**Interfaces:**
- Consumes: `useSelectedInstrument()`、`loadStockCockpit(symbol, asOf?)`。
- Reuses: Advice/证据/风险/失效条件/方案门禁展示规则。
- Produces: 首页单股详情、完整数据分区和股票过滤后的三阶段时间轴。

- [ ] **Step 1: 写首屏详情失败测试**

```tsx
it("shows beginner conclusion before complete deterministic data", async () => {
  render(<StockDecisionCockpit load={() => Promise.resolve(cockpit)} />);
  expect(await screen.findByRole("heading", { name: /浦发银行.*600000/ })).toBeInTheDocument();
  expect(screen.getByText("当前判断")).toBeInTheDocument();
  expect(screen.getByText("支持证据")).toBeInTheDocument();
  expect(screen.getByText("反方证据")).toBeInTheDocument();
  expect(screen.getByText("关键风险")).toBeInTheDocument();
  expect(screen.getByText("失效条件")).toBeInTheDocument();
});

it("never shows a simulation plan when the authoritative gate is not ready", async () => {
  render(<StockDecisionCockpit load={() => Promise.resolve(blockedCockpit)} />);
  expect(await screen.findByText("仅观察")).toBeInTheDocument();
  expect(screen.queryByText("模拟操作计划")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: 实现顶部标的栏和结论区**

顶部展示名称、代码、价格、涨跌幅、行情时间和质量。结论区复用确定性建议，按 `intraday` 优先于 `swing`；无建议时显示分区质量原因，不生成默认建议。风险和反证始终位于任何模拟方案之前。

- [ ] **Step 3: 写完整数据分区与降级测试**

```tsx
it("renders all required sections and keeps unavailable reasons visible", async () => {
  render(<StockDecisionCockpit load={() => Promise.resolve(partialCockpit)} />);
  for (const title of ["实时行情", "量价与趋势", "估值", "基本面", "资金", "新闻与事件", "行业与题材", "回测"]) {
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
  }
  expect(screen.getByText("资金数据尚未接入")).toBeInTheDocument();
});
```

- [ ] **Step 4: 实现分区组件和数据时间**

`CockpitSections` 使用语义 section，不嵌套装饰卡片。每个分区标题旁显示质量；底部显示来源、观察时间和快照 ID。默认显示摘要，详细指标通过原生 `details/summary` 展开。指标名称使用中文映射，原始键只作为开发回退。

- [ ] **Step 5: 写三阶段股票过滤时间轴测试并实现**

```tsx
it("shows only the selected stock across all three phases", async () => {
  render(<PhaseTimeline phases={cockpit.phases} symbol="600000" />);
  expect(screen.getByText("盘前研判")).toBeInTheDocument();
  expect(screen.getByText("盘中变化")).toBeInTheDocument();
  expect(screen.getByText("盘后验证")).toBeInTheDocument();
  expect(screen.queryByText("000001")).not.toBeInTheDocument();
});
```

时间轴显示每版时间、动作、结论、变更字段、前序建议、触发证据和盘后归因。空阶段显示“该股票暂无已验证记录”。

- [ ] **Step 6: 实现响应式排版和请求隔离**

桌面为 `320px` 选择区 + 主区；小于 `900px` 单栏。新请求使用递增序号或 AbortController，旧股票响应不得覆盖新选择。刷新失败保留上次成功内容并标记陈旧。所有新增文字最小 `11px`，手机 `390x844` 无横向溢出。

- [ ] **Step 7: 运行任务测试并提交**

Run:

```powershell
pnpm --filter @qibao/web test -- StockDecisionCockpit.test.tsx StockSelector.test.tsx DecisionWorkbench.test.tsx Dashboard.test.tsx
pnpm --filter @qibao/web build
```

Expected: PASS。

```powershell
git add apps/web/src/features/stock-cockpit apps/web/src/features/dashboard apps/web/src/features/decision-workbench apps/web/src/app/theme.css
git commit -m "feat(web): ship stock decision cockpit"
```

---

### Task 5: 全局深链、生产接线与浏览器验收

**Files:**
- Modify: `apps/web/src/features/news-intelligence/NewsIntelligenceView.tsx`
- Modify: `apps/web/src/features/backtest/BacktestPanel.tsx`
- Modify: `apps/web/src/app/App.tsx`
- Modify: corresponding frontend tests
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-13-v1-roadmap.md`

**Interfaces:**
- Consumes: `useSelectedInstrument()` 和 `?symbol=` URL 契约。
- Produces: A 股新闻、风险、回测深链继承当前股票；转债路由不继承 A 股 symbol。

- [ ] **Step 1: 写跨工作区联动失败测试**

```tsx
it("keeps the selected A-share when opening news and backtest workspaces", async () => {
  window.history.replaceState({}, "", "/?symbol=600000");
  render(<App />);
  await user.click(screen.getByRole("button", { name: /新闻情报/ }));
  expect(screen.getByText("当前标的 600000")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /回测/ }));
  expect(screen.getByDisplayValue("600000")).toBeInTheDocument();
});

it("does not pass the A-share symbol into convertible bonds", async () => {
  window.history.replaceState({}, "", "/?symbol=600000");
  render(<App />);
  await user.click(screen.getByRole("button", { name: /可转债专区/ }));
  expect(window.location.pathname).toBe("/convertible-bonds");
  expect(new URL(window.location.href).searchParams.has("symbol")).toBe(false);
});
```

- [ ] **Step 2: 接入深链并更新准确文档**

新闻、风险和回测仅在 A 股域读取 Provider；各自仍可显示局部筛选，但默认当前股票。README 描述候选+搜索流程、数据降级和非自动交易边界；路线图标记单股驾驶舱完成，但整体 V1 继续保持活动状态。

- [ ] **Step 3: 运行全量验证**

Run:

```powershell
.venv\Scripts\python.exe -m pytest apps/api/tests -q
.venv\Scripts\ruff.exe check apps/api/src apps/api/tests scripts/restore_backup.py
pnpm --filter @qibao/web test
pnpm --filter @qibao/web build
rg -n '�|锟|烫烫|\?\?\?' apps/api/src/qibao_api apps/api/tests apps/web/src README.md
git diff --check
```

Expected: 全部通过，乱码扫描无匹配。

- [ ] **Step 4: 真实 API 验收**

验证一只当前候选和一只目录内榜外 A 股：搜索、驾驶舱、分区降级、三阶段股票过滤和截止时间。不得为了验收写入伪造外部数据。

- [ ] **Step 5: 浏览器验收**

在 `1440x900` 和 `390x844` 检查：

- 候选选择和代码/名称搜索。
- URL 恢复、前进、后退。
- 选择后首屏结论、完整数据分区和三阶段时间轴。
- 快速切换股票时旧响应不覆盖。
- 外部来源失败时保留其他分区并显示原因。
- A 股与可转债隔离。
- 无横向溢出，控制台无新增 error/warn。

- [ ] **Step 6: 提交整合**

```powershell
git add apps/api apps/web/src README.md docs
git commit -m "feat(cockpit): integrate global stock workflow"
```

## Completion Gate

- [ ] 搜索、候选、自选和 URL 都能选择同一个全局 A 股标的。
- [ ] 当前标的在首页、A 股研究、新闻、风险和回测间保持一致。
- [ ] 单股驾驶舱完整显示结论、证据、反证、风险、失效条件和十个数据分区。
- [ ] 三阶段只展示选中股票并保留完整盘中变化流。
- [ ] 缺失数据不清空整个页面、不虚构值，并显示明确原因。
- [ ] 可转债不读取 A 股 symbol，也不出现在 A 股搜索结果。
- [ ] 全量测试、构建、乱码扫描、桌面/手机浏览器验收全部通过。
