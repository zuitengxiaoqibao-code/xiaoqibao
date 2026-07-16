import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SelectedInstrumentProvider } from "../instrument-selection/SelectedInstrumentProvider";
import { StockDecisionCockpit } from "./StockDecisionCockpit";
import type { Advice } from "../decision-workbench/types";
import type { CockpitSection, StockCockpitSnapshot } from "./types";

const advice = (overrides: Partial<Advice> = {}): Advice => ({
  advice_id: "advice-intraday", snapshot_id: "cycle-2", asset: "a_share", symbol: "600000", horizon: "intraday", observation_state: "watching",
  action: "simulated_plan", conclusion: "等待量价确认后继续观察", confidence: "0.72",
  supporting_evidence: [{ evidence_id: "e1", source: "tencent", snapshot_id: "quote-1", summary: "价格位于短期均线上方", observed_at: "2026-07-15T10:29:00+08:00" }],
  contrary_evidence: [{ evidence_id: "e2", source: "bars", snapshot_id: "bars-1", summary: "成交量尚未放大", observed_at: "2026-07-15T10:28:00+08:00" }],
  risks: ["大盘回落可能压制银行板块"], invalidation_conditions: ["跌破 10 日均线"],
  plain_language_explanation: "信号有支持，但确认条件还不完整。", quantitative_result: {}, ai_interpretation_id: null, strategy_version: "strategy-v1",
  created_at: "2026-07-15T10:30:00+08:00", simulation_plan_id: "missing-plan", risk_decision_id: "missing-gate",
  simulation_gate: null, previous_advice_id: "advice-premarket", changed_fields: ["conclusion", "risks"], ...overrides,
});

const section = (status: CockpitSection["status"] = "ready", reason: string | null = null): CockpitSection => ({
  status, source: "fixture", observed_at: status === "unavailable" ? null : "2026-07-15T10:29:00+08:00",
  snapshot_id: status === "unavailable" ? null : "diagnosis-1", reason,
  payload: { explanation: "已读取确定性指标", metrics: { price: "10.25", change_percent: "1.49", pe_ttm: "5.8" }, evidence_ids: ["e1"] },
});

const snapshot = (overrides: Partial<StockCockpitSnapshot> = {}): StockCockpitSnapshot => ({
  symbol: "600000", as_of: "2026-07-15", cutoff: "2026-07-15T10:30:00+08:00", overall_quality: "partial",
  instrument: { symbol: "600000", name: "浦发银行", exchange: "sh", observed_at: "2026-07-15T10:29:00+08:00", quote_quality: "ready" },
  candidate_membership: ["short_term"], current_advice: [advice()],
  assessment: {
    assessment_id: "assessment-1", symbol: "600000", action: "observe", conclusion: "行情与日线数据可用且无风险阻断，保持观察。", confidence: "0.75",
    supporting_evidence: [{ evidence_id: "assessment-e1", source: "tencent", snapshot_id: "quote-1", summary: "行情快照有效", observed_at: "2026-07-15T10:29:00+08:00" }],
    contrary_evidence: [], risks: ["市场与基本面条件可能在截止时间后变化。"], invalidation_conditions: ["任一核心分区状态或指标发生变化。"],
    simulation_eligible: false, authorized_simulation_advice_id: null,
    authorized_simulation_plan_id: null, generated_at: "2026-07-15T10:30:00+08:00",
  },
  sections: {
    market: section(), price_volume: section(), trend: section(), valuation: section(), fundamentals: section(),
    funds: section("unavailable", "fund_data_not_connected"), news: section(), industry: section(), risk: section(),
    backtest: section("unavailable", "backtest_not_run"),
  },
  phases: {
    premarket: { advice: [advice({ advice_id: "advice-premarket", snapshot_id: "cycle-1", horizon: "swing", action: "observe", conclusion: "盘前等待", previous_advice_id: null, changed_fields: [] })], change_stream: [{ snapshot_id: "cycle-1", sequence: 1, generated_at: "2026-07-15T09:00:00+08:00", status: "ready" }] },
    intraday: { advice: [advice()], change_stream: [{ snapshot_id: "cycle-2", sequence: 2, generated_at: "2026-07-15T10:30:00+08:00", status: "partial" }] },
    postclose: { advice: [], change_stream: [] },
  }, ...overrides,
});

function renderCockpit(load: (symbol: string, asOf?: string, signal?: AbortSignal) => Promise<StockCockpitSnapshot> = () => Promise.resolve(snapshot())) {
  window.history.replaceState({}, "", "/?symbol=600000");
  return render(<SelectedInstrumentProvider><StockDecisionCockpit load={load} /></SelectedInstrumentProvider>);
}

describe("StockDecisionCockpit", () => {
  it("shows an immediate assessment for a non-candidate stock", async () => {
    const nonCandidateCockpit = snapshot({
      candidate_membership: [], current_advice: [],
      assessment: {
        ...snapshot().assessment, action: "wait", conclusion: "等待趋势样本补足", confidence: "0.4",
        supporting_evidence: [], contrary_evidence: [], risks: [], invalidation_conditions: [], simulation_eligible: false,
      },
    });
    renderCockpit(() => Promise.resolve(nonCandidateCockpit));
    expect(await screen.findByText("等待趋势样本补足")).toBeInTheDocument();
    expect(screen.getByText("非当前候选，不生成模拟买卖方案")).toBeInTheDocument();
    expect(screen.getByText("暂无已验证支持证据")).toBeInTheDocument();
    expect(screen.getByText("当前研判未列出风险")).toBeInTheDocument();
    expect(screen.getByText("当前研判未列出失效条件")).toBeInTheDocument();
    expect(screen.queryByText("当前没有可展示建议")).not.toBeInTheDocument();
  });

  it("shows the beginner conclusion before all deterministic sections", async () => {
    renderCockpit();
    expect(await screen.findByRole("heading", { name: /浦发银行.*600000/ })).toBeInTheDocument();
    for (const text of ["当前判断", "支持证据", "反方证据", "关键风险", "失效条件"]) expect(screen.getByText(text)).toBeInTheDocument();
    const headings = screen.getAllByRole("heading").map((item) => item.textContent);
    expect(headings.indexOf("当前判断")).toBeLessThan(headings.indexOf("实时行情"));
    expect(screen.getAllByText("10.25").length).toBeGreaterThan(0);
  });

  it("never shows a simulation plan without an authoritative ready gate", async () => {
    renderCockpit();
    expect(await screen.findByText(/仅观察/)).toBeInTheDocument();
    expect(screen.queryByText("模拟操作计划")).not.toBeInTheDocument();
  });

  it("prioritizes the deterministic intraday advice over swing advice", async () => {
    const swing = advice({ advice_id: "swing", horizon: "swing", conclusion: "波段继续观察", created_at: "2026-07-15T10:31:00+08:00" });
    const intraday = advice({ advice_id: "intraday", horizon: "intraday", conclusion: "盘中等待确认", created_at: "2026-07-15T10:30:00+08:00" });
    renderCockpit(() => Promise.resolve(snapshot({ current_advice: [swing, intraday] })));
    expect(await screen.findByRole("heading", { name: "盘中等待确认" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "波段继续观察" })).not.toBeInTheDocument();
  });

  it("renders all ten sections and explicit unavailable reasons", async () => {
    renderCockpit();
    for (const title of ["实时行情", "量价", "趋势", "估值", "基本面", "资金", "新闻与事件", "行业与题材", "风险", "回测"]) {
      expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    }
    expect(screen.getByText("资金数据尚未接入")).toBeInTheDocument();
    expect(screen.getByText("尚未为该股票运行回测")).toBeInTheDocument();
    expect(screen.getAllByText(/来源：fixture/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("已读取确定性指标").length).toBeGreaterThan(0);
  });

  it("shows partial and stale section reasons instead of hiding degradation", async () => {
    const partial = snapshot();
    partial.sections.trend = { ...section("partial", "trend_window_incomplete"), payload: { explanation: "短周期不足", metrics: {} } };
    partial.sections.news = { ...section("stale", "news_snapshot_stale"), payload: { explanation: "新闻快照较旧", metrics: {} } };
    renderCockpit(() => Promise.resolve(partial));
    expect(await screen.findByText("trend_window_incomplete")).toBeInTheDocument();
    expect(screen.getByText("news_snapshot_stale")).toBeInTheDocument();
  });

  it("uses market section time and quality instead of directory identity time", async () => {
    const data = snapshot();
    data.instrument.observed_at = "2026-07-15T08:00:00+08:00";
    data.sections.market = { ...section("stale", "market_snapshot_stale"), observed_at: "2026-07-15T10:12:00+08:00" };
    renderCockpit(() => Promise.resolve(data));
    expect(await screen.findByText("行情陈旧")).toBeInTheDocument();
    expect(screen.getAllByText(/2026\/7\/15 10:12:00/).length).toBeGreaterThan(0);
  });

  it("shows candidate membership and only reveals a plan reference after every authoritative gate passes", async () => {
    const gated = advice({
      simulation_gate: { quote_state: "ready", compliance_state: "ready", evidence_state: "ready", risk_state: "approve", risk_decision_id: "missing-gate", compliance_snapshot_id: "compliance-1" },
    });
    renderCockpit(() => Promise.resolve(snapshot({ candidate_membership: ["short_term", "swing"], assessment: { ...snapshot().assessment, simulation_eligible: true, authorized_simulation_advice_id: "advice-intraday", authorized_simulation_plan_id: "missing-plan" }, current_advice: [gated] })));
    expect(await screen.findByText("短线候选")).toBeInTheDocument();
    expect(screen.getByText("波段候选")).toBeInTheDocument();
    expect(screen.getByText("模拟操作计划")).toBeInTheDocument();
    expect(screen.getByText(/missing-plan/)).toBeInTheDocument();
    for (const label of ["行情门禁", "合规门禁", "证据门禁", "风控门禁"]) expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("does not loosen the backend simulation eligibility", async () => {
    const gated = advice({
      simulation_gate: { quote_state: "ready", compliance_state: "ready", evidence_state: "ready", risk_state: "approve", risk_decision_id: "missing-gate", compliance_snapshot_id: "compliance-1" },
    });
    renderCockpit(() => Promise.resolve(snapshot({ assessment: { ...snapshot().assessment, simulation_eligible: false }, current_advice: [gated] })));
    expect(await screen.findByText("后端未返回权威模拟方案引用")).toBeInTheDocument();
    expect(screen.queryByText("模拟操作计划")).not.toBeInTheDocument();
  });

  it("shows only the advice named by the authoritative simulation reference", async () => {
    const intraday = advice({ advice_id: "intraday-unverified", conclusion: "伪造盘中方案", simulation_plan_id: "forged-plan" });
    const swing = advice({ advice_id: "swing-authorized", horizon: "swing", conclusion: "波段权威方案", simulation_plan_id: "swing-plan" });
    renderCockpit(() => Promise.resolve(snapshot({
      candidate_membership: ["short_term", "swing"], current_advice: [intraday, swing],
      assessment: { ...snapshot().assessment, simulation_eligible: true, authorized_simulation_advice_id: "swing-authorized", authorized_simulation_plan_id: "swing-plan" },
    })));
    expect(await screen.findByRole("heading", { name: "波段权威方案" })).toBeInTheDocument();
    expect(screen.getByText("swing-plan")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "伪造盘中方案" })).not.toBeInTheDocument();
    expect(screen.queryByText("forged-plan")).not.toBeInTheDocument();
  });

  it("keeps the last successful snapshot and marks it stale after refresh failure", async () => {
    const load = vi.fn().mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error("链路中断"));
    renderCockpit(load);
    await screen.findByRole("heading", { name: /浦发银行/ });
    fireEvent.click(screen.getByRole("button", { name: "刷新驾驶舱" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("链路中断");
    expect(screen.getByRole("heading", { name: /浦发银行/ })).toBeInTheDocument();
    expect(screen.getByText("当前内容已陈旧")).toBeInTheDocument();
  });

  it("does not retain live data when a historical context request fails", async () => {
    const load = vi.fn().mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error("历史快照不存在"));
    window.history.replaceState({}, "", "/?symbol=600000");
    const view = render(<SelectedInstrumentProvider><StockDecisionCockpit load={load} /></SelectedInstrumentProvider>);
    await screen.findByRole("heading", { name: /浦发银行/ });
    view.rerender(<SelectedInstrumentProvider><StockDecisionCockpit load={load} asOf="2026-07-14" /></SelectedInstrumentProvider>);
    expect(await screen.findByRole("alert")).toHaveTextContent("历史快照不存在");
    expect(screen.queryByRole("heading", { name: /浦发银行/ })).not.toBeInTheDocument();
  });

  it("does not let an old symbol response replace a newer selection", async () => {
    let resolveOld!: (value: StockCockpitSnapshot) => void;
    const load = vi.fn((symbol: string) => symbol === "600000" ? new Promise<StockCockpitSnapshot>((resolve) => { resolveOld = resolve; }) : Promise.resolve(snapshot({ symbol: "000001", instrument: { ...snapshot().instrument, symbol: "000001", name: "平安银行", exchange: "sz" } })));
    renderCockpit(load);
    window.history.pushState({}, "", "/?symbol=000001");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(await screen.findByRole("heading", { name: /平安银行.*000001/ })).toBeInTheDocument();
    resolveOld(snapshot());
    expect(screen.queryByRole("heading", { name: /浦发银行/ })).not.toBeInTheDocument();
  });
});
