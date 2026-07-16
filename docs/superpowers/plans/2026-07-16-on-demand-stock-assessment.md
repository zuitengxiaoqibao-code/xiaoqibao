# 任意 A 股即时研判实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让任何已验证 A 股立即获得确定性研判，并仅对通过候选与权威门禁的股票展示模拟方案。

**Architecture:** 后端新增独立即时研判器，消费现有驾驶舱十个分区并产生冻结评估，不写三阶段账本。驾驶舱聚合即时评估与候选账本；OpenAI 兼容网关只为确定性结果生成可验证解释。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLite、React 19、TypeScript、Vitest、httpx。

## Global Constraints

- AI 不得修改价格、动作、评分、风险或门禁。
- 非候选股票不得生成买入价、仓位、止损或模拟计划。
- 所有证据满足 `observed_at <= cutoff`。
- 缺失数据必须显示具体原因，不得显示空白。
- A 股与可转债状态、接口和数据模型保持隔离。
- 中文文件使用 `apply_patch`，完成后执行乱码扫描。

---

### Task 1: 修复盘前候选冻结时间

**Files:**
- Modify: `apps/api/src/qibao_api/shangshu/decision_runtime.py`
- Modify: `apps/api/src/qibao_api/zhongshu/premarket_decision.py`
- Test: `apps/api/tests/zhongshu/test_premarket_decision.py`

**Interfaces:**
- Produces: `RepositoryCandidateFactorSource.candidates(as_of, cutoff=None) -> CandidateInputSnapshot`
- Consumes later: 盘前服务读取截止时间冻结的候选输入。

- [ ] **Step 1: 写失败测试，固定补跑不会因实际时钟晚于 09:20 被阻断**

```python
def test_premarket_uses_requested_cutoff_for_candidate_capture():
    source = RepositoryCandidateFactorSource(service, clock=lambda: LATE_TIME)
    snapshot = source.candidates(TRADE_DATE, cutoff=WINDOW_END)
    assert snapshot.captured_at == WINDOW_END
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/zhongshu/test_premarket_decision.py -q`

- [ ] **Step 3: 传递显式 cutoff，并保留历史边界校验**

```python
def candidates(self, as_of: date, cutoff: datetime | None = None):
    board = self.candidate_service.candidates(as_of)
    return CandidateInputSnapshot(
        board=board,
        captured_at=cutoff or self.clock(),
        history_available=board.universe_status == "ready",
    )
```

盘前服务调用 `candidate_service.candidates(trading_date, cutoff=window_end)`；其他调用保持默认时钟。

- [ ] **Step 4: 运行盘前与决策测试并提交**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/zhongshu apps/api/tests/shangshu -q`

Commit: `fix(decisions): freeze premarket candidate cutoff`

---

### Task 2: 实现即时单股确定性研判

**Files:**
- Create: `apps/api/src/qibao_api/a_shares/assessment.py`
- Create: `apps/api/tests/a_shares/test_assessment.py`
- Modify: `apps/api/src/qibao_api/a_shares/cockpit.py`
- Modify: `apps/api/tests/a_shares/test_cockpit.py`

**Interfaces:**
- Produces: `StockAssessment`, `DeterministicStockAssessor.assess(symbol, sections, candidate_membership, cutoff)`
- Produces action: `Literal["observe", "wait", "avoid"]`

- [ ] **Step 1: 写三类动作的失败测试**

```python
def test_waits_when_trend_sample_is_unavailable():
    result = assessor.assess("600519", sections(no_bars=True), (), CUTOFF)
    assert result.action == "wait"
    assert "日线" in result.conclusion

def test_avoids_when_authoritative_risk_is_blocked():
    result = assessor.assess("600519", sections(risk="blocked"), (), CUTOFF)
    assert result.action == "avoid"

def test_observes_complete_non_candidate_without_inventing_plan():
    result = assessor.assess("600519", complete_sections(), (), CUTOFF)
    assert result.action == "observe"
    assert result.simulation_eligible is False
```

- [ ] **Step 2: 运行测试并确认模块不存在**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_assessment.py -q`

- [ ] **Step 3: 定义冻结契约并实现规则优先级**

```python
class StockAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)
    assessment_id: str
    symbol: AShareCode
    action: Literal["observe", "wait", "avoid"]
    conclusion: str
    confidence: Decimal = Field(ge=0, le=1)
    supporting_evidence: tuple[EvidenceReference, ...]
    contrary_evidence: tuple[EvidenceReference, ...]
    risks: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    simulation_eligible: bool
    generated_at: AwareDatetime
```

优先级固定为：风险阻断 `avoid` > 行情或日线不足 `wait` > 其他 `observe`。证据 ID 由来源、观察时间和指标内容确定性哈希生成。

- [ ] **Step 4: 驾驶舱响应新增 `assessment`，不写决策账本**

```python
assessment = self.assessor.assess(symbol, sections, membership, effective_cutoff)
return StockCockpitSnapshot(..., assessment=assessment)
```

- [ ] **Step 5: 运行聚焦测试并提交**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_assessment.py apps/api/tests/a_shares/test_cockpit.py apps/api/tests/routes/test_research.py -q`

Commit: `feat(research): add deterministic stock assessment`

---

### Task 3: 驾驶舱展示即时研判与机会资格

**Files:**
- Modify: `apps/web/src/features/stock-cockpit/types.ts`
- Modify: `apps/web/src/features/stock-cockpit/StockDecisionCockpit.tsx`
- Modify: `apps/web/src/features/stock-cockpit/StockDecisionCockpit.test.tsx`
- Modify: `apps/web/src/app/theme.css`

**Interfaces:**
- Consumes: `StockCockpitSnapshot.assessment`
- Preserves: `current_advice` 和 `simulation_gate` 作为候选交易层。

- [ ] **Step 1: 写非候选也有研判的失败测试**

```tsx
it("shows an immediate assessment for a non-candidate stock", async () => {
  renderCockpit(nonCandidateCockpit);
  expect(await screen.findByText("等待趋势样本补足")).toBeInTheDocument();
  expect(screen.getByText("非当前候选，不生成模拟买卖方案")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --filter @qibao/web test -- StockDecisionCockpit.test.tsx`

- [ ] **Step 3: 首屏优先渲染 assessment，再渲染候选账本建议**

无账本建议时不得显示“当前没有可展示建议”；改为展示即时研判。候选资格和四项门禁逐项显示，非候选明确说明不会生成价位或仓位。

- [ ] **Step 4: 运行前端测试和构建并提交**

Run: `pnpm --filter @qibao/web test && pnpm --filter @qibao/web build`

Commit: `feat(web): show on-demand stock assessment`

---

### Task 4: OpenAI 兼容解释网关

**Files:**
- Create: `apps/api/src/qibao_api/a_shares/assessment_ai.py`
- Create: `apps/api/tests/a_shares/test_assessment_ai.py`
- Modify: `apps/api/src/qibao_api/settings.py`
- Modify: `apps/api/src/qibao_api/main.py`
- Modify: `apps/api/src/qibao_api/a_shares/cockpit.py`

**Interfaces:**
- Produces: `AssessmentAIExplanation`, `OpenAICompatibleAssessmentGateway.explain(assessment, evidence)`
- Config: `QIBAO_AI_BASE_URL`, `QIBAO_AI_API_KEY`, `QIBAO_AI_MODEL`

- [ ] **Step 1: 写未配置、非法证据引用和正常解释测试**

```python
def test_unconfigured_ai_preserves_deterministic_assessment():
    result = gateway(api_key=None).explain(assessment, evidence)
    assert result.status == "unconfigured"

def test_rejects_ai_evidence_ids_outside_frozen_input():
    result = gateway(response={"evidence_ids": ["invented"]}).explain(assessment, evidence)
    assert result.status == "invalid"
```

- [ ] **Step 2: 实现兼容 `/chat/completions` 的严格 JSON 请求**

只发送必要证据，响应模型禁止额外字段；超时、HTTP 错误和解析错误映射为状态，不抛掉确定性 assessment。

- [ ] **Step 3: 聚合响应增加可空 `ai_explanation` 和明确状态**

不得让 AI 修改 `assessment.action`、`confidence` 或 `simulation_eligible`。

- [ ] **Step 4: 运行测试并提交**

Run: `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests/a_shares/test_assessment_ai.py apps/api/tests/a_shares/test_cockpit.py -q`

Commit: `feat(ai): explain deterministic stock assessments`

---

### Task 5: 全量验证与真实浏览器验收

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-13-v1-roadmap.md`
- Modify: corresponding API/frontend tests when acceptance exposes a regression

- [ ] **Step 1: 更新文档**

说明任意股票即时研判、候选交易层、AI 环境变量、非自动交易边界和缺失数据降级。

- [ ] **Step 2: 运行全量验证**

```powershell
$env:QIBAO_DATA_DIR = Join-Path $env:TEMP 'qibao-assessment-final'
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests -q
apps/api/.venv/Scripts/python.exe -m ruff check apps/api/src apps/api/tests scripts/restore_backup.py
pnpm --filter @qibao/web test
pnpm --filter @qibao/web build
rg -n '�|锟|烫烫|\?\?\?' apps/api/src/qibao_api apps/api/tests apps/web/src README.md
git diff --check
```

- [ ] **Step 3: 真实 API 验收**

验证一只候选股与两只非候选股均有 assessment；非候选无模拟计划；盘前补跑不被毫秒时间差阻断；AI 未配置时 assessment 保留。

- [ ] **Step 4: 浏览器验收**

在 `1440x900` 和 `390x844` 检查搜索、快速切股、即时研判、候选门禁、历史日期、AI 状态、转债隔离、无横向溢出和无控制台错误。

- [ ] **Step 5: 提交整合**

Commit: `feat(cockpit): deliver on-demand stock decisions`

## Completion Gate

- [ ] 任意有效 A 股都有即时确定性研判。
- [ ] 非候选没有虚构交易方案。
- [ ] 候选门禁和三阶段账本保持权威。
- [ ] 盘前补跑时间边界正确。
- [ ] AI 故障不影响确定性结论。
- [ ] 全量测试、构建、乱码扫描和双尺寸浏览器验收通过。
