# 三阶段决策台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有新闻简报、A 股候选、风险、模拟交易和审计能力汇总为可追溯的盘前研判、盘中监测和盘后复盘决策台。

**Architecture:** 新增独立决策契约和追加式 SQLite 仓储，阶段服务只引用冻结的候选、新闻、风险与结果快照。盘前、盘中、盘后分别由小型服务生成同一契约；前端通过单一查询 API 读取阶段版本，不直接拼接各部门原始接口。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLite、DuckDB、React 19、TypeScript、Vitest。

## Global Constraints

- A 股是默认主域；可转债保持独立入口、模型、候选池和专属指标。
- 不支持期货，不连接真实券商，不自动下单。
- 数值计算、评分、价格区间和风险参数只由确定性程序产生；AI 只做归纳和解释。
- 所有建议必须显示支持证据、反方证据、风险、失效条件、数据时间和版本。
- 盘前、盘中和盘后不得读取窗口结束后的输入。
- 历史阶段快照、建议和模拟方案只追加，不更新或删除。
- V1 使用 60 秒重点标的、3 至 5 分钟候选宇宙的分层轮询；接口保留未来流式实现。
- 中文文件只使用 `apply_patch` 手工修改，完成后执行乱码扫描。

---

### Task 1: 不可变决策契约与追加式仓储

**Files:**
- Create: `apps/api/src/qibao_api/contracts/decision.py`
- Create: `apps/api/src/qibao_api/shangshu/decision_repository.py`
- Create: `apps/api/tests/contracts/test_decision.py`
- Create: `apps/api/tests/shangshu/test_decision_repository.py`
- Modify: `apps/api/src/qibao_api/gongbu/backup_service.py`
- Modify: `apps/api/tests/gongbu/test_backup_service.py`

**Interfaces:**
- Produces: `DecisionCycleSnapshot`, `AdviceCard`, `SimulationPlan`, `EvidenceReference`, `DecisionCycleAggregate`, `DecisionRepository.append_cycle(...)`, `DecisionRepository.cycles(...)`, `DecisionRepository.latest(...)`。
- Consumes later: all phase services persist complete cycle aggregates through this repository; API reads only verified aggregates.

- [ ] **Step 1: 写失败契约测试，固定证据、反证和未来时间边界**

```python
def test_advice_requires_risk_and_invalidation_disclosures() -> None:
    with pytest.raises(ValidationError):
        AdviceCard(
            advice_id="advice-1", snapshot_id="cycle-1", asset="a_share",
            symbol="600000", horizon="intraday", observation_state="watching",
            action="observe", conclusion="等待量价确认", confidence="0.62",
            supporting_evidence=(evidence("quote-1"),), contrary_evidence=(),
            risks=(), invalidation_conditions=(), quantitative_result={},
            created_at=NOW, strategy_version="decision-v1",
        )

def test_cycle_rejects_inputs_after_window_end() -> None:
    with pytest.raises(ValidationError, match="after window end"):
        cycle(source_observed_at=WINDOW_END + timedelta(seconds=1))
```

- [ ] **Step 2: 运行契约测试并确认模块不存在**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/contracts/test_decision.py -q`

Expected: FAIL，错误指向 `qibao_api.contracts.decision` 不存在。

- [ ] **Step 3: 实现冻结契约和模拟方案门禁字段**

```python
DecisionPhase = Literal["premarket", "intraday", "postclose"]
AdviceAction = Literal["observe", "wait", "avoid", "invalidated", "simulated_plan"]

class EvidenceReference(BaseModel):
    model_config = ConfigDict(frozen=True)
    evidence_id: NonBlank
    source: NonBlank
    observed_at: AwareDatetime
    snapshot_id: NonBlank
    summary: NonBlank

class AdviceCard(BaseModel):
    model_config = ConfigDict(frozen=True)
    advice_id: NonBlank
    snapshot_id: NonBlank
    asset: AssetKind
    symbol: str
    horizon: Literal["intraday", "swing"]
    observation_state: NonBlank
    action: AdviceAction
    conclusion: NonBlank
    confidence: Decimal = Field(ge=0, le=1)
    supporting_evidence: tuple[EvidenceReference, ...]
    contrary_evidence: tuple[EvidenceReference, ...]
    risks: tuple[NonBlank, ...]
    invalidation_conditions: tuple[NonBlank, ...]
    plain_language_explanation: str | None = None
    quantitative_result: dict[str, Decimal | str | None]
    ai_interpretation_id: str | None = None
    risk_decision_id: str | None = None
    simulation_plan_id: str | None = None
    previous_advice_id: str | None = None
    changed_fields: tuple[NonBlank, ...] = ()
    strategy_version: NonBlank
    created_at: AwareDatetime

class DecisionCycleAggregate(BaseModel):
    model_config = ConfigDict(frozen=True)
    snapshot: DecisionCycleSnapshot
    advice: tuple[AdviceCard, ...]
    plans: tuple[SimulationPlan, ...] = ()
```

`DecisionCycleSnapshot` 包含规格定义的交易日、阶段、序号、时间窗口、市场状态、质量、来源引用、候选/新闻/风险引用、输入哈希、前序快照和状态；必须验证所有输入证据 `observed_at <= window_end <= generated_at`，盘前不得包含 `phase="intraday"` 的输入。`SimulationPlan` 必须同时具有 `advice_id`、`risk_decision_id`、`compliance_snapshot_id` 和有效期。

- [ ] **Step 4: 写失败仓储测试，固定追加写、哈希链和事务原子性**

```python
def test_cycle_is_append_only_and_chain_verified(tmp_path: Path) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    repository.append_cycle(cycle(sequence=1), advice=(advice(),), plans=())
    repository.connection.execute(
        "UPDATE decision_cycles SET payload='{}' WHERE snapshot_id='cycle-1'"
    )
    with pytest.raises(sqlite3.IntegrityError):
        repository.connection.commit()

def test_append_rolls_back_when_advice_reference_is_invalid(tmp_path: Path) -> None:
    repository = DecisionRepository(tmp_path / "decisions.sqlite3")
    with pytest.raises(ValueError, match="snapshot"):
        repository.append_cycle(cycle(), advice=(advice(snapshot_id="other"),), plans=())
    assert repository.cycles(trading_date=TRADE_DATE) == []
```

- [ ] **Step 5: 实现规范哈希、前序哈希和完整性读取**

建立 `decision_cycles`、`decision_advice`、`decision_plans` 三张表及禁止更新/删除触发器。每个阶段链按 `(trading_date, phase, sequence)` 排序；`canonical_hash` 绑定模型 JSON，`previous_hash` 绑定前一版本。`append_cycle()` 使用一个事务写入快照、建议和方案；`cycles()` 每次读取重新计算内容哈希并验证链、外键引用和当前序号连续性，失败抛出 `DecisionIntegrityError`。

- [ ] **Step 6: 将决策仓储加入备份和语义恢复演练**

在 `BackupService` 的 SQLite 备份清单中加入决策数据库，并在恢复验证器中调用 `DecisionRepository.cycles()`。测试篡改后的决策库不能通过恢复演练。

- [ ] **Step 7: 运行任务测试并提交**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/contracts/test_decision.py apps/api/tests/shangshu/test_decision_repository.py apps/api/tests/gongbu/test_backup_service.py -q`

Expected: PASS。

```powershell
git add apps/api/src/qibao_api/contracts/decision.py apps/api/src/qibao_api/shangshu/decision_repository.py apps/api/src/qibao_api/gongbu/backup_service.py apps/api/tests
git commit -m "feat(decisions): add immutable cycle ledger"
```

### Task 2: 盘前研判聚合与受约束 AI 解释

**Files:**
- Create: `apps/api/src/qibao_api/zhongshu/decision_ai.py`
- Create: `apps/api/src/qibao_api/zhongshu/premarket_decision.py`
- Create: `apps/api/tests/zhongshu/test_decision_ai.py`
- Create: `apps/api/tests/zhongshu/test_premarket_decision.py`
- Modify: `apps/api/src/qibao_api/shangshu/scheduler.py`
- Modify: `apps/api/tests/shangshu/test_scheduler.py`

**Interfaces:**
- Consumes: `AShareDiagnosisService.candidates(as_of, limit)`, verified news events and interpretations, compliance feature state, deterministic risk summary, `DecisionRepository`.
- Produces: `PremarketDecisionService.run(trading_date, now) -> DecisionCycleAggregate`，其中包含已持久化的快照、建议和零个或多个方案。

- [ ] **Step 1: 写失败测试，禁止盘前使用开盘后输入并固定部分降级**

```python
def test_premarket_excludes_inputs_after_market_window(tmp_path: Path) -> None:
    service = make_service(news=(event_at("2026-07-15T09:31:00+08:00"),))
    result = service.run(TRADE_DATE, now=dt("2026-07-15T09:20:00+08:00"))
    assert result.news_event_ids == ()

def test_premarket_keeps_quantitative_advice_when_ai_is_unavailable() -> None:
    result = make_service(ai=UnavailableDecisionAI()).run(TRADE_DATE, now=NOW)
    assert result.status == "partial"
    assert result.ai_status == "unavailable"
    assert result.advice[0].plain_language_explanation is None
```

- [ ] **Step 2: 运行测试并确认盘前服务不存在**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/zhongshu/test_premarket_decision.py -q`

Expected: FAIL，错误指向 `premarket_decision` 不存在。

- [ ] **Step 3: 写失败 AI 测试，固定引用范围和数值禁区**

```python
async def test_ai_rejects_unreferenced_fact_and_numeric_plan() -> None:
    provider = Provider('{"summary":"建议10.20买入","statements":[{"kind":"fact","text":"政策利好","evidence_ids":[]}]}')
    result = DecisionAIGateway(provider).explain(request())
    assert result.status == "unavailable"
    assert result.explanation is None
    assert result.invalid_output_count == 1
```

- [ ] **Step 4: 实现 AI 结构校验和确定性盘前建议**

`DecisionAIProvider.complete(request: dict) -> str` 是运行在专用调度线程中的同步端口。`DecisionAIGateway` 只接受 `summary` 和带证据 ID 的 `fact | interpretation` 语句；拒绝输出中的价格区间、仓位、止损和止盈字段。`PremarketDecisionService` 根据候选榜、诊断、已验证新闻、反方引用和风险摘要生成 `observe | wait | avoid`；任何基础来源缺失时不得生成 `simulated_plan`。

- [ ] **Step 5: 将盘前调度改为生成决策周期而非只有简报计数**

调度器在现有盘前简报成功后调用盘前决策服务。相同输入哈希的补跑返回已有快照 ID；输入变化时追加新序号。任一阶段失败记录错误事件，不覆盖已完成版本。

- [ ] **Step 6: 运行任务测试并提交**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/zhongshu/test_decision_ai.py apps/api/tests/zhongshu/test_premarket_decision.py apps/api/tests/shangshu/test_scheduler.py -q`

Expected: PASS。

```powershell
git add apps/api/src/qibao_api/zhongshu apps/api/src/qibao_api/shangshu/scheduler.py apps/api/tests
git commit -m "feat(decisions): generate evidence-backed premarket advice"
```

### Task 3: 盘中分层轮询、变化检测与模拟方案门禁

**Files:**
- Create: `apps/api/src/qibao_api/gongbu/market_feed.py`
- Create: `apps/api/src/qibao_api/shangshu/intraday_monitor.py`
- Create: `apps/api/src/qibao_api/bingbu/simulation_plan.py`
- Create: `apps/api/tests/gongbu/test_market_feed.py`
- Create: `apps/api/tests/shangshu/test_intraday_monitor.py`
- Create: `apps/api/tests/bingbu/test_simulation_plan.py`
- Modify: `apps/api/src/qibao_api/shangshu/scheduler.py`
- Modify: `apps/api/tests/shangshu/test_scheduler.py`

**Interfaces:**
- Produces: `MarketFeedPort.snapshot(symbol)`, `MarketFeedPort.snapshot_many(symbols)`, optional `MarketFeedPort.subscribe(symbols)` capability; `IntradayMonitor.check(now)`, `SimulationPlanBuilder.build(...)`.
- Consumes: latest decision cycle, A-share candidate universe, Tencent snapshot adapter, risk and compliance decisions.

- [ ] **Step 1: 写失败端口测试，固定轮询实现与未来流式能力边界**

```python
async def test_polling_feed_exposes_no_stream_capability() -> None:
    feed = PollingMarketFeed(source=source())
    assert feed.capabilities == frozenset({"snapshot", "snapshot_many"})
    with pytest.raises(NotImplementedError):
        await feed.subscribe(("600000",))
```

- [ ] **Step 2: 写失败监测测试，固定 60 秒、完整宇宙间隔和退避**

```python
def test_monitor_checks_focus_at_sixty_seconds_and_universe_at_three_minutes() -> None:
    monitor = make_monitor(focus_interval=60, universe_interval=180)
    first = monitor.due(dt("10:00:00"))
    second = monitor.due(dt("10:01:00"))
    third = monitor.due(dt("10:03:00"))
    assert first == {"focus", "universe"}
    assert second == {"focus"}
    assert third == {"focus", "universe"}

def test_repeated_source_failures_back_off_without_hiding_staleness() -> None:
    monitor = make_monitor(source=FailingSource())
    state = monitor.check(NOW)
    assert state.mode == "degraded"
    assert state.next_focus_interval_seconds == 120
    assert state.last_error_code == "source_unavailable"
```

- [ ] **Step 3: 运行测试并确认端口和监测器不存在**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/gongbu/test_market_feed.py apps/api/tests/shangshu/test_intraday_monitor.py -q`

Expected: FAIL，错误指向新模块不存在。

- [ ] **Step 4: 实现分层轮询状态机和建议差异追加**

轮询状态保存 `last_focus_success_at`、`last_universe_success_at`、连续失败次数、当前间隔和下次到期时间。重点间隔从 60 秒开始，完整宇宙间隔在 180 至 300 秒内；失败时按 `60, 120, 240, 300` 秒封顶。仅当建议动作、结论、风险、失效条件、候选归属或模拟方案门禁变化时追加盘中快照；`changed_fields` 必须精确列出变化字段。

- [ ] **Step 5: 写失败模拟方案测试，固定全部门禁和确定性数值**

```python
def test_plan_is_absent_when_any_gate_is_not_ready() -> None:
    for gate in ("quote", "compliance", "evidence", "risk"):
        context = ready_context().model_copy(update={gate: "blocked"})
        assert SimulationPlanBuilder().build(context) is None

def test_plan_prices_come_from_quantitative_levels() -> None:
    plan = SimulationPlanBuilder().build(ready_context(levels=levels("10.10", "9.70")))
    assert plan.watch_price_low == Decimal("10.10")
    assert plan.stop_loss == Decimal("9.70")
    assert sum(plan.tranches) <= Decimal("1")
```

- [ ] **Step 6: 实现模拟方案构建器并接入盘中调度**

价格和仓位只读取确定性 `QuantitativeLevels`。构建器要求行情、合规、证据和刑部决策全为 ready/approve；否则返回 `None` 并将门禁原因写入建议风险。调度器持久化轮询状态，重启后从最后成功时间恢复，不重复发出内容相同的快照。

- [ ] **Step 7: 运行任务测试并提交**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/gongbu/test_market_feed.py apps/api/tests/shangshu/test_intraday_monitor.py apps/api/tests/bingbu/test_simulation_plan.py apps/api/tests/shangshu/test_scheduler.py -q`

Expected: PASS。

```powershell
git add apps/api/src/qibao_api/gongbu/market_feed.py apps/api/src/qibao_api/shangshu apps/api/src/qibao_api/bingbu/simulation_plan.py apps/api/tests
git commit -m "feat(decisions): monitor intraday advice changes"
```

### Task 4: 盘后结果评估和次日观察清单

**Files:**
- Create: `apps/api/src/qibao_api/zhongshu/postclose_review.py`
- Create: `apps/api/tests/zhongshu/test_postclose_review.py`
- Modify: `apps/api/src/qibao_api/shangshu/postclose_context.py`
- Modify: `apps/api/tests/shangshu/test_postclose_context.py`

**Interfaces:**
- Consumes: 当日冻结 `AdviceCard`、当日窗口内行情结果、模拟成交、风险决定和东厂发现。
- Produces: `AdviceOutcome`, `PostcloseReviewService.run(trading_date, now)` and next-day observations persisted in a postclose cycle.

- [ ] **Step 1: 写失败测试，禁止评估不存在或晚生成的建议**

```python
def test_postclose_reviews_only_advice_frozen_before_market_close() -> None:
    service = make_service(advice=(before_close(), after_close()))
    result = service.run(TRADE_DATE, NOW)
    assert [item.advice_id for item in result.outcomes] == [before_close().advice_id]

def test_unverifiable_outcome_is_not_scored_as_wrong() -> None:
    result = make_service(market_result=UnavailableResult()).run(TRADE_DATE, NOW)
    assert result.outcomes[0].status == "unverifiable"
    assert result.outcomes[0].error_attribution == "data_unavailable"
```

- [ ] **Step 2: 运行测试并确认复盘服务不存在**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/zhongshu/test_postclose_review.py -q`

Expected: FAIL，错误指向 `postclose_review` 不存在。

- [ ] **Step 3: 实现确定性结果状态和归因**

`AdviceOutcome.status` 固定为 `correct | wrong | invalidated | risk_blocked | unverifiable`；归因固定为 `data_issue | news_misread | trend_failure | risk_event | rule_block | simulation_execution | data_unavailable`。结果计算只使用建议创建后至市场收盘的数据，并引用原建议、原快照和结果输入哈希。

- [ ] **Step 4: 生成次日观察清单但不自动继承失效逻辑**

只有 `correct` 或仍未触发失效条件的 `unverifiable` 建议可进入次日观察；`wrong`、`invalidated` 和 `risk_blocked` 必须记录撤销或重新验证原因。AI 可以解释归因，但不能修改确定性状态。

- [ ] **Step 5: 运行任务测试并提交**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/zhongshu/test_postclose_review.py apps/api/tests/shangshu/test_postclose_context.py -q`

Expected: PASS。

```powershell
git add apps/api/src/qibao_api/zhongshu/postclose_review.py apps/api/src/qibao_api/shangshu/postclose_context.py apps/api/tests
git commit -m "feat(decisions): review frozen daily advice"
```

### Task 5: 决策 API 与三阶段首页

**Files:**
- Create: `apps/api/src/qibao_api/routes/decisions.py`
- Create: `apps/api/tests/routes/test_decisions.py`
- Modify: `apps/api/src/qibao_api/dependencies.py`
- Modify: `apps/api/src/qibao_api/main.py`
- Create: `apps/web/src/features/decision-workbench/types.ts`
- Create: `apps/web/src/features/decision-workbench/api.ts`
- Create: `apps/web/src/features/decision-workbench/DecisionWorkbench.tsx`
- Create: `apps/web/src/features/decision-workbench/DecisionWorkbench.test.tsx`
- Modify: `apps/web/src/app/App.tsx`
- Modify: `apps/web/src/features/dashboard/Dashboard.tsx`
- Modify: `apps/web/src/features/dashboard/Dashboard.test.tsx`
- Modify: `apps/web/src/app/theme.css`

**Interfaces:**
- Produces: `GET /api/v1/decisions/current`, `GET /api/v1/decisions/{trading_date}`, `POST /api/v1/decisions/{phase}/{trading_date}/run` and the default `/` decision workbench.
- Consumes: verified `DecisionRepository` aggregates; manual run delegates to the scheduler and never writes directly from the route.

- [ ] **Step 1: 写失败 API 测试，固定阶段选择、历史版本和错误映射**

```python
def test_current_decision_returns_phase_versions_and_server_time() -> None:
    response = client.get("/api/v1/decisions/current")
    assert response.status_code == 200
    assert response.json()["current_phase"] == "intraday"
    assert set(response.json()["phases"]) == {"premarket", "intraday", "postclose"}
    assert response.json()["server_time"].endswith("+08:00")

def test_integrity_failure_is_503_and_hides_payload() -> None:
    response = corrupt_client.get("/api/v1/decisions/current")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "decision_integrity_error"
    assert "advice" not in response.text
```

- [ ] **Step 2: 实现依赖、查询 API 和受调度器控制的手动运行**

`current` 使用服务器北京时间和交易日历选择阶段；非交易日返回最近交易日盘后版本并标记 `market_session="closed"`。无快照返回 `200` 和明确 `phase_status="empty"`。存储损坏映射 `503`，未来交易日映射 `422`，未确认交易日手动运行映射 `409`。

- [ ] **Step 3: 写失败组件测试，固定观察、AI、风险和模拟方案层级**

```tsx
it("keeps risks and contrary evidence visible beside AI advice", async () => {
  render(<DecisionWorkbench loadCurrent={() => Promise.resolve(partialCycle)} />);
  expect(await screen.findByRole("heading", { name: "盘前研判" })).toBeInTheDocument();
  expect(screen.getByText("等待量价确认")).toBeInTheDocument();
  expect(screen.getByText("反方证据")).toBeInTheDocument();
  expect(screen.getByText("主要风险")).toBeInTheDocument();
});

it("does not render a simulation plan before every gate passes", async () => {
  render(<DecisionWorkbench loadCurrent={() => Promise.resolve(blockedCycle)} />);
  expect(await screen.findByText("仅观察")).toBeInTheDocument();
  expect(screen.queryByText("模拟操作方案")).not.toBeInTheDocument();
});
```

- [ ] **Step 4: 运行组件测试并确认工作台不存在**

Run: `pnpm --filter @qibao/web test -- DecisionWorkbench.test.tsx`

Expected: FAIL，错误指向 `DecisionWorkbench` 不存在。

- [ ] **Step 5: 实现阶段状态、观察池、变化流和证据抽屉**

默认 `/` 渲染决策台，顶部按 API 的 `current_phase` 选中阶段，并允许手动切换历史阶段。首屏固定呈现今日总判断、AI 状态、短线/波段观察、主要风险和反方证据。建议详情展开后显示来源、数据时间、策略/规则/模型版本和失效条件。只有 `action="simulated_plan"` 且方案引用齐全时显示模拟方案。

- [ ] **Step 6: 实现加载、空、部分降级、阻断、AI 不可用和轮询降频状态**

前端不在浏览器自行推断质量；按 API 状态逐一渲染。加载失败提供重试；旧请求通过请求序号隔离。盘中状态显示最后成功时间、下次检查和当前间隔；页面轮询只重新读取聚合 API，不直接调用全市场行情源。

- [ ] **Step 7: 接入导航、前进后退和响应式布局**

“今日工作台”继续指向 `/`，但内容替换为三阶段决策台。A 股研究、转债、部门和运维深链保持不变。桌面双栏；`760px` 以下单列，风险与反方证据在 AI 分析之后、模拟方案之前，不使用横向表格。

- [ ] **Step 8: 运行全量测试和浏览器验收**

Run:

```powershell
.venv\Scripts\python.exe -m pytest apps/api/tests -q
.venv\Scripts\ruff.exe check apps/api/src apps/api/tests scripts/restore_backup.py
pnpm --filter @qibao/web test
pnpm --filter @qibao/web build
rg -n '�|锟|烫烫|\?\?\?' apps/api/src/qibao_api apps/api/tests apps/web/src README.md
git diff --check
```

Expected: all commands pass;乱码扫描无匹配。

浏览器验收：在 `1440x900` 与 `390x844` 检查 `/`；验证自动阶段、手动切换、观察建议、AI 不可用、反方证据、风险、降频、模拟方案门禁、前进后退和无水平溢出。检查控制台无 error/warn。

- [ ] **Step 9: 更新路线图和提交**

更新 `docs/superpowers/plans/2026-07-13-v1-roadmap.md` 和 `README.md`，将三阶段决策台标为已实现，并保留吏部资金中心、户部、兵部和尚书省独立页面为后续部门工作区任务。

```powershell
git add apps/api apps/web/src docs README.md
git commit -m "feat(decisions): ship three-phase decision workbench"
```

## Completion Gate

- [ ] 四个阶段切片均已独立审查，所有 P0/P1 已修复。
- [ ] 真实盘前、盘中、盘后 API 至少各生成一个可验证快照；若当前时间窗口未开放，使用固定测试时钟完成运行验收且不得伪造外部数据。
- [ ] A 股观察池与可转债域未混排。
- [ ] AI 不可用时确定性建议仍可读，且无虚构解释。
- [ ] 历史建议可通过输入快照、哈希链和版本引用完整恢复。
- [ ] 整体 V1 目标仍保持活动，直到部门工作区和最终生产审计全部完成。
