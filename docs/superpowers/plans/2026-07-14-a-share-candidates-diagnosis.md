# A 股候选池与完整诊断实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 A 股主域提供可重复的短线榜、波段榜和证据可追溯的单股完整诊断，并在独立工作区中清晰展示行情、量价、趋势、估值、基本面、事件、行业与风险。

**Architecture:** 候选宇宙只取本地 DuckDB 已同步且历史长度合格的 A 股，确定性因子只使用候选时点及之前数据。单股诊断复用本地日线、腾讯行情、通达信财务快照和已入库新闻；每个分区独立报告来源、数据时间和可用状态，部分来源失败时保留其余确定性结果并降级，不伪造字段。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、DuckDB、mootdx、httpx、React 19、TypeScript、Vitest。

## Global Constraints

- A 股和可转债模型、因子、候选池、API 与页面保持完全隔离。
- 数值因子和排名由确定性程序计算；AI 不参与打分。
- 候选计算禁止未来数据泄漏，必须记录 `as_of`、数据源和因子版本。
- 外部来源缺失时返回明确的 `unavailable` 或 `partial`，不得填充推测值。
- 东财不是本切片的批量候选来源；行情优先腾讯，历史与财务优先 mootdx。
- 第一版不连接券商、不自动下单，所有结论仅为观察建议。

---

### Task 1: 确定性 A 股因子和双榜排名

**Files:**
- Create: `apps/api/src/qibao_api/a_shares/__init__.py`
- Create: `apps/api/src/qibao_api/a_shares/models.py`
- Create: `apps/api/src/qibao_api/a_shares/factors.py`
- Create: `apps/api/src/qibao_api/a_shares/candidates.py`
- Test: `apps/api/tests/a_shares/test_factors.py`
- Test: `apps/api/tests/a_shares/test_candidates.py`

**Interfaces:**
- Consumes: `DailyBar` 按交易日升序排列的不可变序列。
- Produces: `FactorSnapshot`、`CandidateEntry`、`CandidateBoard`，以及 `build_factor_snapshot(bars, as_of)` 和 `rank_candidates(snapshots, horizon, limit)`。

- [x] **Step 1: 写失败测试，固定因子口径和时间边界**

```python
def test_factor_snapshot_uses_only_bars_on_or_before_as_of() -> None:
    bars = make_bars(80) + [make_bar(date(2026, 7, 15), close="999")]
    result = build_factor_snapshot(bars, as_of=date(2026, 7, 14))
    assert result.as_of == date(2026, 7, 14)
    assert result.close != Decimal("999")
    assert result.factor_version == "a-share-factors-v1"

def test_factor_snapshot_rejects_less_than_sixty_bars() -> None:
    with pytest.raises(InsufficientHistoryError):
        build_factor_snapshot(make_bars(59), as_of=date(2026, 7, 14))
```

- [x] **Step 2: 运行测试并确认因缺少模块而失败**

Run: `.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_factors.py -q`

Expected: FAIL，错误指向 `qibao_api.a_shares.factors` 不存在。

- [x] **Step 3: 实现无未来数据的因子快照**

```python
class FactorSnapshot(BaseModel):
    symbol: str
    as_of: date
    close: Decimal
    return_5d: Decimal
    return_20d: Decimal
    distance_ma20: Decimal
    volume_ratio_5_20: Decimal
    volatility_20d: Decimal
    drawdown_60d: Decimal
    liquidity_amount_20d: Decimal
    factor_version: Literal["a-share-factors-v1"] = "a-share-factors-v1"
    source: str

def build_factor_snapshot(bars: Sequence[DailyBar], as_of: date) -> FactorSnapshot:
    eligible = sorted((bar for bar in bars if bar.trade_date <= as_of), key=lambda bar: bar.trade_date)
    if len(eligible) < 60:
        raise InsufficientHistoryError("at least 60 historical bars are required")
    return calculate_from(eligible[-60:])
```

- [x] **Step 4: 写失败测试，固定短线和波段榜排序及剔除规则**

```python
def test_short_term_and_swing_boards_rank_differently() -> None:
    board = build_candidate_board([momentum_snapshot(), stable_trend_snapshot()], limit=10)
    assert board.short_term[0].symbol == momentum_snapshot().symbol
    assert board.swing[0].symbol == stable_trend_snapshot().symbol
    assert board.short_term[0].score_breakdown.keys() == {
        "momentum", "volume", "trend", "liquidity", "risk_penalty"
    }

def test_candidate_board_excludes_insufficient_liquidity() -> None:
    board = build_candidate_board([illiquid_snapshot()], limit=10)
    assert board.short_term == []
    assert board.exclusions[0].reason_code == "insufficient_liquidity"
```

- [x] **Step 5: 实现透明分数明细与稳定排序**

短线权重固定为 `5 日动量 30% + 量比 25% + MA20 趋势 20% + 流动性 15% - 波动惩罚 10%`；波段权重固定为 `20 日动量 25% + MA20 趋势 30% + 流动性 15% - 波动惩罚 10% - 60 日回撤惩罚 20%`。所有横截面输入用 winsorize 后的百分位分数，分数相同时按股票代码升序，保证重复运行一致。

- [x] **Step 6: 运行任务测试并提交**

Run: `.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares -q`

Expected: PASS。

```bash
git add apps/api/src/qibao_api/a_shares apps/api/tests/a_shares
git commit -m "feat(a-shares): add deterministic candidate factors"
```

### Task 2: 本地候选查询与完整诊断聚合

**Files:**
- Modify: `apps/api/src/qibao_api/storage/bar_repository.py`
- Modify: `apps/api/src/qibao_api/gongbu/tencent_quotes.py`
- Create: `apps/api/src/qibao_api/a_shares/fundamentals.py`
- Create: `apps/api/src/qibao_api/a_shares/diagnosis.py`
- Test: `apps/api/tests/storage/test_bar_repository.py`
- Test: `apps/api/tests/gongbu/test_tencent_quotes.py`
- Test: `apps/api/tests/a_shares/test_diagnosis.py`

**Interfaces:**
- Consumes: `BarRepository.symbols_with_history(minimum_bars, as_of)`、腾讯扩展行情、mootdx 财务快照、`NewsRepository.events()`。
- Produces: `AShareDiagnosisService.candidates(as_of, limit)` 和异步 `diagnose(symbol, as_of)`。

- [x] **Step 1: 写失败测试，要求仓储一次查询候选宇宙和批量日线**

```python
def test_repository_returns_only_symbols_with_enough_history(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    repository.upsert(make_symbol_bars("600000", 80) + make_symbol_bars("000001", 40))
    assert repository.symbols_with_history(60, date(2026, 7, 14)) == ["600000"]
    assert len(repository.latest_many(["600000"], 60, date(2026, 7, 14))["600000"]) == 60
```

- [x] **Step 2: 实现参数化 DuckDB 查询，禁止拼接股票代码**

新增 `symbols_with_history()` 和 `latest_many()`；查询统一持有仓储锁，`as_of` 作为 SQL 参数，并验证输入全为合法 A 股代码。

- [x] **Step 3: 写失败测试并扩展腾讯估值字段解析**

```python
def test_tencent_snapshot_parses_valuation_without_field_guessing() -> None:
    snapshot = parse_tencent_snapshot(load_fixture("tencent_600000.txt"), "tencent")
    assert snapshot.pe_ttm == Decimal("6.32")
    assert snapshot.pb == Decimal("0.58")
    assert snapshot.turnover_rate == Decimal("0.42")
    assert snapshot.market_cap_yi == Decimal("3120.50")
```

解析器继续严格按 GBK 解码；空字符串和 `--` 映射为 `None`，字段 46 才是 PB。保留现有 `Quote` 接口，新增 `TencentMarketSnapshot`，避免破坏实时管线。

- [x] **Step 4: 写失败测试，覆盖部分来源失败的诊断**

```python
async def test_diagnosis_keeps_local_analysis_when_fundamentals_fail() -> None:
    result = await service(finance_source=FailingFinanceSource()).diagnose("600000", AS_OF)
    assert result.sections["trend"].status == "ready"
    assert result.sections["fundamentals"].status == "unavailable"
    assert result.overall_status == "partial"
    assert result.missing_data == ["fundamentals"]
    assert result.action == "observe"
```

- [x] **Step 5: 实现分区诊断与确定性风险结论**

诊断分区固定为 `market`、`price_volume`、`trend`、`valuation`、`fundamentals`、`events`、`industry`、`risk`。每个分区包含 `status`、`observed_at`、`source`、`metrics`、`evidence_ids` 和新手解释；强制保留空值，不把 `0` 当成缺失。新闻只使用冻结事件中明确关联 `(a_share, symbol)` 的引用。

- [x] **Step 6: 运行任务测试并提交**

Run: `.venv/Scripts/python.exe -m pytest apps/api/tests/storage/test_bar_repository.py apps/api/tests/gongbu/test_tencent_quotes.py apps/api/tests/a_shares -q`

Expected: PASS。

```bash
git add apps/api/src/qibao_api/storage/bar_repository.py apps/api/src/qibao_api/gongbu/tencent_quotes.py apps/api/src/qibao_api/a_shares apps/api/tests
git commit -m "feat(a-shares): aggregate evidence-backed diagnoses"
```

### Task 3: A 股候选与诊断 API、审计和降级

**Files:**
- Modify: `apps/api/src/qibao_api/dependencies.py`
- Modify: `apps/api/src/qibao_api/main.py`
- Modify: `apps/api/src/qibao_api/routes/research.py`
- Create: `apps/api/src/qibao_api/a_shares/repository.py`
- Test: `apps/api/tests/routes/test_research.py`
- Test: `apps/api/tests/a_shares/test_repository.py`

**Interfaces:**
- Produces: `GET /api/v1/a-shares/candidates?as_of=YYYY-MM-DD&limit=20`、`GET /api/v1/a-shares/{symbol}/diagnosis?as_of=YYYY-MM-DD`。
- Persists: append-only candidate snapshots and diagnosis snapshots with canonical SHA-256 input hash.

- [ ] **Step 1: 写失败路由测试，固定响应与资产隔离**

```python
def test_a_share_candidates_return_separate_short_and_swing_lists() -> None:
    response = client.get("/api/v1/a-shares/candidates?as_of=2026-07-14&limit=20")
    assert response.status_code == 200
    assert response.json()["asset"] == "a_share"
    assert set(response.json()) >= {"short_term", "swing", "as_of", "factor_version"}

def test_convertible_bond_code_never_reaches_a_share_diagnosis() -> None:
    assert client.get("/api/v1/a-shares/113001/diagnosis").status_code == 422
```

- [ ] **Step 2: 写失败仓储测试，固定追加写和防篡改行为**

```python
def test_candidate_snapshot_is_append_only_and_hash_verified(tmp_path: Path) -> None:
    repository = AShareResearchRepository(tmp_path / "a-share-research.sqlite3")
    snapshot_id = repository.append_candidate_board(board())
    assert repository.get_candidate_board(snapshot_id) == board()
    with pytest.raises(sqlite3.IntegrityError):
        repository.connection.execute("UPDATE candidate_snapshots SET payload='{}'")
```

- [ ] **Step 3: 实现服务依赖、路由和错误映射**

候选池无任何满足历史要求的股票时返回 `200` 和空榜，同时包含 `universe_status="empty"`；本地仓损坏返回 `503`；单个补充来源失败仍返回 `200 partial`；基础行情与本地日线同时不可用时返回 `503`，不得返回伪诊断。

- [ ] **Step 4: 运行路由、仓储与全后端测试**

Run: `.venv/Scripts/python.exe -m pytest apps/api/tests/routes/test_research.py apps/api/tests/a_shares -q`

Expected: PASS。

Run: `.venv/Scripts/python.exe -m pytest apps/api/tests -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交 API 切片**

```bash
git add apps/api/src/qibao_api apps/api/tests
git commit -m "feat(a-shares): expose audited research workspace APIs"
```

### Task 4: 独立 A 股研究工作区

**Files:**
- Create: `apps/web/src/features/a-shares/types.ts`
- Create: `apps/web/src/features/a-shares/api.ts`
- Create: `apps/web/src/features/a-shares/AShareResearchView.tsx`
- Create: `apps/web/src/features/a-shares/AShareResearchView.test.tsx`
- Modify: `apps/web/src/features/dashboard/Dashboard.tsx`
- Modify: `apps/web/src/app/App.tsx`
- Modify: `apps/web/src/app/theme.css`

**Interfaces:**
- Consumes: 候选池和诊断 API。
- Produces: 深链 `/a-shares`，短线榜/波段榜页签，点击候选后打开同页诊断工作区。

- [ ] **Step 1: 写失败组件测试，覆盖榜单、证据和降级**

```tsx
it("keeps short-term and swing candidates separate", async () => {
  render(<AShareResearchView loadCandidates={loadBoards} loadDiagnosis={loadDiagnosis} />);
  expect(await screen.findByRole("tab", { name: "短线榜" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "波段榜" }));
  expect(screen.getByText("波段稳定度")).toBeInTheDocument();
});

it("shows unavailable fundamentals without hiding trend evidence", async () => {
  render(<AShareResearchView loadCandidates={loadBoards} loadDiagnosis={loadPartial} />);
  fireEvent.click(await screen.findByRole("button", { name: /600000/ }));
  expect(await screen.findByText("基本面数据暂不可用")).toBeInTheDocument();
  expect(screen.getByText("MA20 趋势")).toBeInTheDocument();
  expect(screen.getByText(/数据截至/)).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试并确认组件不存在而失败**

Run: `pnpm --filter @qibao/web test -- AShareResearchView.test.tsx`

Expected: FAIL，错误指向组件模块不存在。

- [ ] **Step 3: 实现独立工作区与稳定布局**

顶部使用紧凑的 A 股主域状态栏；主体左侧为可扫描榜单，右侧为诊断详情。移动端改为榜单后接诊断的单列流，不使用横向表格。分数必须可展开查看因子贡献；每个诊断分区显示来源和时间；空数据、加载、局部降级与完全错误分别呈现。

- [ ] **Step 4: 接入导航和深链**

新增侧栏 `A 股研究` 入口并映射 `/a-shares`；保留今日工作台，且可转债入口仍指向 `/convertible-bonds`。浏览器前进后退必须恢复正确工作区。

- [ ] **Step 5: 运行前端测试、构建和浏览器验收**

Run: `pnpm --filter @qibao/web test`

Expected: 全部 PASS。

Run: `pnpm --filter @qibao/web build`

Expected: exit 0。

浏览器验收：在 `1440x900` 与 `390x844` 检查 `/a-shares`，确认无水平溢出、中文不截断、短线/波段切换稳定、部分来源失败不清空其他诊断分区。

- [ ] **Step 6: 编码扫描、全量验证并提交**

Run: `rg -n '�|锟|烫烫|\?\?\?' apps/api/src/qibao_api apps/api/tests apps/web/src README.md`

Expected: 无匹配。

Run: `git diff --check`

Expected: exit 0。

```bash
git add apps/web/src apps/api README.md
git commit -m "feat(a-shares): add candidate and diagnosis workspace"
```
