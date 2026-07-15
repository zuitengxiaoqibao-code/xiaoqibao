import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DecisionWorkbench } from "./DecisionWorkbench";
import type { DecisionResponse, PlanReadiness } from "./types";

const emptySlot = { phase_status: "empty" as const, quality: "empty" as const, aggregate_version: null, ai_status: "not_requested" as const, advice: [], evidence: [], plans: [], plan_readiness: {} };

function response(overrides: Partial<DecisionResponse> = {}): DecisionResponse {
  return {
    server_time: "2026-07-15T10:30:00+08:00", trading_date: "2026-07-15",
    current_phase: "intraday", market_session: "open",
    phases: { premarket: emptySlot, intraday: emptySlot, postclose: emptySlot },
    polling: { focus_interval_seconds: 60, universe_interval_seconds: 240, stale_after_seconds: 180, next_check_seconds: 60 },
    ...overrides,
  };
}

describe("DecisionWorkbench", () => {
  it("auto-selects the API phase and exposes all historical phase tabs", async () => {
    render(<DecisionWorkbench loadCurrent={() => Promise.resolve(response())} />);

    expect(await screen.findByRole("tab", { name: "盘中监测", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "盘前研判" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "盘后复盘" })).toBeInTheDocument();
    expect(screen.getByText("当前阶段暂无决策快照")).toBeInTheDocument();
  });

  it("does not let a stale phase request replace the latest selection", async () => {
    let resolveFirst!: (value: DecisionResponse) => void;
    const first = new Promise<DecisionResponse>((resolve) => { resolveFirst = resolve; });
    const loadDate = vi.fn()
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce(response({ current_phase: "postclose" }));
    render(<DecisionWorkbench loadCurrent={() => Promise.resolve(response())} loadDate={loadDate} />);
    await screen.findByRole("tab", { name: "盘中监测", selected: true });

    fireEvent.change(screen.getByLabelText("交易日期"), { target: { value: "2026-07-14" } });
    fireEvent.change(screen.getByLabelText("交易日期"), { target: { value: "2026-07-13" } });
    resolveFirst(response({ current_phase: "premarket" }));

    expect(await screen.findByRole("tab", { name: "盘后复盘", selected: true })).toBeInTheDocument();
  });

  it("shows a simulation plan only when reciprocal references and gates are complete", async () => {
    const advice = {
      advice_id: "a1", snapshot_id: "s1", asset: "a_share" as const, symbol: "600000", horizon: "swing" as const, observation_state: "watching",
      action: "simulated_plan" as const, conclusion: "仅用于模拟观察", confidence: "0.72",
      supporting_evidence: [{ evidence_id: "e1", source: "tencent", snapshot_id: "q1", summary: "价格快照有效", observed_at: "2026-07-15T10:29:00+08:00" }],
      contrary_evidence: [], risks: ["市场波动"], invalidation_conditions: ["跌破观察区间"],
      plain_language_explanation: "条件满足后也只进入模拟计划。", quantitative_result: {}, ai_interpretation_id: null, strategy_version: "strategy-v1", created_at: "2026-07-15T10:30:00+08:00",
      simulation_plan_id: "p1", risk_decision_id: "r1", simulation_gate: { quote_state: "ready" as const, compliance_state: "ready" as const, evidence_state: "ready" as const, risk_state: "approve" as const, risk_decision_id: "r1", compliance_snapshot_id: "c1" }, previous_advice_id: null, changed_fields: [],
    };
    const plan = { plan_id: "p1", advice_id: "a1", risk_decision_id: "r1", compliance_snapshot_id: "c1", watch_price_low: "10", watch_price_high: "10.2", stop_loss: "9.8", take_profit: ["10.6"], tranches: ["0.2"], max_position: "0.2", invalidation_conditions: ["跌破观察区间"], valid_from: "2026-07-15T10:30:00+08:00", valid_until: "2026-07-15T15:00:00+08:00", strategy_version: "strategy-v1", risk_version: "risk-v1", compliance_version: "compliance-v1" };
    const intraday = { ...emptySlot, phase_status: "ready" as const, quality: "ready" as const, aggregate_version: "s1", ai_status: "ready" as const, advice: [advice], plans: [plan], plan_readiness: { a1: { ready: true, reasons: [], quote_state: "ready" as const, compliance_state: "ready" as const, evidence_state: "ready" as const, risk_state: "approve" as const } } };
    render(<DecisionWorkbench loadCurrent={() => Promise.resolve(response({ phases: { premarket: emptySlot, intraday, postclose: emptySlot } }))} />);

    expect(await screen.findByText("模拟操作计划")).toBeInTheDocument();
    expect(screen.getByText("反向证据：暂无已验证记录")).toBeInTheDocument();
    expect(screen.getByText(/strategy-v1/)).toBeInTheDocument();
  });

  it("offers retry after an aggregate API failure", async () => {
    const loadCurrent = vi.fn().mockRejectedValueOnce(new Error("决策链路暂不可用")).mockResolvedValueOnce(response());
    render(<DecisionWorkbench loadCurrent={loadCurrent} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("决策链路暂不可用");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("当前阶段暂无决策快照")).toBeInTheDocument();
  });

  it("retries the current endpoint after current mode has populated a date", async () => {
    const loadCurrent = vi.fn().mockResolvedValueOnce(response()).mockRejectedValueOnce(new Error("current failed")).mockResolvedValueOnce(response());
    const loadDate = vi.fn();
    render(<DecisionWorkbench loadCurrent={loadCurrent} loadDate={loadDate} />);
    await screen.findByRole("tab", { name: "盘中监测" });
    await loadCurrent.mock.results[0].value;
    fireEvent.click(screen.getByRole("button", { name: "刷新当前" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("current failed");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await screen.findByText("当前阶段暂无决策快照");
    expect(loadCurrent).toHaveBeenCalledTimes(3);
    expect(loadDate).not.toHaveBeenCalled();
  });

  it.each<[string, PlanReadiness | undefined]>([
    ["blocked quote", { ready: false, reasons: ["quote_blocked"], quote_state: "blocked", compliance_state: "ready", evidence_state: "ready", risk_state: "approve" }],
    ["rejected risk", { ready: false, reasons: ["risk_rejected"], quote_state: "ready", compliance_state: "ready", evidence_state: "ready", risk_state: "reject" }],
    ["missing gate", undefined],
  ])("hides a simulation plan for %s", async (_label, readiness) => {
    const advice = {
      advice_id: "a1", snapshot_id: "s1", asset: "a_share" as const, symbol: "600000", horizon: "swing" as const, observation_state: "watching",
      action: "simulated_plan" as const, conclusion: "观察", confidence: "0.7",
      supporting_evidence: [{ evidence_id: "e1", source: "tencent", snapshot_id: "q1", summary: "有效", observed_at: "2026-07-15T10:29:00+08:00" }],
      contrary_evidence: [], risks: ["波动"], invalidation_conditions: ["条件变化"], plain_language_explanation: null, quantitative_result: {}, ai_interpretation_id: null, strategy_version: "v1",
      created_at: "2026-07-15T10:30:00+08:00", simulation_plan_id: "p1", risk_decision_id: "r1", simulation_gate: null, previous_advice_id: null, changed_fields: [],
    };
    const plan = { plan_id: "p1", advice_id: "a1", risk_decision_id: "r1", compliance_snapshot_id: "c1", watch_price_low: "10", watch_price_high: "10.2", stop_loss: "9.8", take_profit: ["10.6"], tranches: ["0.2"], max_position: "0.2", invalidation_conditions: ["条件变化"], valid_from: "2026-07-15T10:30:00+08:00", valid_until: "2026-07-15T15:00:00+08:00", strategy_version: "v1", risk_version: "r1", compliance_version: "c1" };
    const readinessMap: Record<string, PlanReadiness> = readiness ? { a1: readiness } : {};
    const slot = { ...emptySlot, phase_status: "partial" as const, quality: "partial" as const, aggregate_version: "s1", ai_status: "unavailable" as const, advice: [advice], plans: [plan], plan_readiness: readinessMap };
    render(<DecisionWorkbench loadCurrent={() => Promise.resolve(response({ phases: { premarket: emptySlot, intraday: slot, postclose: emptySlot } }))} />);

    expect(await screen.findByText("当前仅供观察，不形成模拟操作计划。")).toBeInTheDocument();
    expect(screen.queryByText("模拟操作计划")).not.toBeInTheDocument();
  });

  it("uses linked tabs with roving focus and arrow-key navigation", async () => {
    render(<DecisionWorkbench loadCurrent={() => Promise.resolve(response())} />);
    const current = await screen.findByRole("tab", { name: "盘中监测" });
    expect(current).toHaveAttribute("aria-controls", "decision-panel-intraday");
    expect(current).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(current, { key: "ArrowRight" });
    const next = screen.getByRole("tab", { name: "盘后复盘", selected: true });
    expect(next).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "decision-tab-postclose");
  });

  it("preserves a manual phase selection across polling reloads", async () => {
    vi.useFakeTimers();
    const loadCurrent = vi.fn().mockResolvedValue(response());
    render(<DecisionWorkbench loadCurrent={loadCurrent} />);
    await vi.runOnlyPendingTimersAsync();
    fireEvent.click(screen.getByRole("tab", { name: "盘前研判" }));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(screen.getByRole("tab", { name: "盘前研判", selected: true })).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("keeps polling the current endpoint until a historical date is explicitly selected", async () => {
    vi.useFakeTimers();
    const loadCurrent = vi.fn().mockResolvedValue(response());
    const loadDate = vi.fn().mockResolvedValue(response());
    render(<DecisionWorkbench loadCurrent={loadCurrent} loadDate={loadDate} />);
    await vi.runOnlyPendingTimersAsync();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(loadCurrent).toHaveBeenCalledTimes(2);
    expect(loadDate).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("shows degraded zero-advice, AI-unavailable, and stale polling semantics", async () => {
    const slot = { ...emptySlot, phase_status: "partial" as const, quality: "partial" as const, aggregate_version: "s1", ai_status: "unavailable" as const, generated_at: "2026-07-15T10:20:00+08:00" };
    render(<DecisionWorkbench loadCurrent={() => Promise.resolve(response({ phases: { premarket: emptySlot, intraday: slot, postclose: emptySlot } }))} />);
    expect(await screen.findByText("数据部分可用")).toBeInTheDocument();
    expect(screen.getByText("AI 不可用")).toBeInTheDocument();
    expect(screen.getByText("聚合数据已过期")).toBeInTheDocument();
    expect(screen.getByText("当前阶段没有可展示建议")).toBeInTheDocument();
    expect(screen.getByText(/焦点 60s/)).toBeInTheDocument();
    expect(screen.getByText(/全域 240s/)).toBeInTheDocument();
  });

  it("explains ordered change lineage with symbols, fields, conclusions, and evidence", async () => {
    const transition = (id: string, symbol: string, conclusion: string, previous: string | null, fields: string[], reason: string) => ({
      advice_id: id, snapshot_id: `snapshot-${id}`, asset: "a_share" as const, symbol, horizon: "intraday" as const, observation_state: "watching",
      action: "wait" as const, conclusion, confidence: "0.5",
      supporting_evidence: [{ evidence_id: `e-${id}`, source: "tencent", snapshot_id: `q-${id}`, summary: reason, observed_at: "2026-07-15T10:29:00+08:00" }],
      contrary_evidence: [], risks: ["波动风险"], invalidation_conditions: ["条件变化"], plain_language_explanation: null, quantitative_result: {}, ai_interpretation_id: null,
      risk_decision_id: null, simulation_plan_id: null, simulation_gate: null, strategy_version: "v1", created_at: "2026-07-15T10:30:00+08:00",
      previous_advice_id: previous, changed_fields: fields,
    });
    const first = transition("a2", "600000", "等待量价确认", "a1", ["action", "conclusion"], "成交量尚未确认");
    const second = transition("a3", "000001", "风险条件变化", "a0", ["risks"], "风险规则触发");
    const slot = {
      ...emptySlot, phase_status: "partial" as const, quality: "partial" as const,
      aggregate_version: "intra-2", ai_status: "not_requested" as const,
      advice: [first, second],
      change_stream: [
        { snapshot_id: "intra-1", sequence: 1, generated_at: "2026-07-15T10:30:00+08:00", delta_advice: [first], delta_plans: [] },
        { snapshot_id: "intra-2", sequence: 2, generated_at: "2026-07-15T11:00:00+08:00", delta_advice: [second], delta_plans: [] },
      ],
    };
    render(<DecisionWorkbench loadCurrent={() => Promise.resolve(response({ phases: { premarket: emptySlot, intraday: slot, postclose: emptySlot } }))} />);

    const versions = await screen.findAllByText(/变化版本 #/);
    expect(versions.map((item) => item.textContent)).toEqual([expect.stringContaining("#1"), expect.stringContaining("#2")]);
    expect(screen.getByText(/600000 · 等待 · 等待量价确认/)).toBeInTheDocument();
    expect(screen.getByText(/变更字段：action、conclusion/)).toBeInTheDocument();
    expect(screen.getByText(/前序建议：a1/)).toBeInTheDocument();
    expect(screen.getByText("成交量尚未确认")).toBeInTheDocument();
    expect(screen.getByText(/000001 · 等待 · 风险条件变化/)).toBeInTheDocument();
    expect(screen.getByText("风险规则触发")).toBeInTheDocument();
  });

  it("strictly filters advice and change-stream records to the selected A-share", async () => {
    const selected = {
      advice_id: "selected", snapshot_id: "selected-snapshot", asset: "a_share" as const, symbol: "600000", horizon: "intraday" as const, observation_state: "watching", action: "wait" as const,
      conclusion: "浦发等待", confidence: "0.5", supporting_evidence: [{ evidence_id: "e-selected", source: "tencent", snapshot_id: "q1", summary: "浦发证据", observed_at: "2026-07-15T10:29:00+08:00" }], contrary_evidence: [], risks: ["波动"], invalidation_conditions: ["条件变化"], plain_language_explanation: null, quantitative_result: {}, ai_interpretation_id: null, risk_decision_id: null, simulation_plan_id: null, simulation_gate: null, previous_advice_id: null, changed_fields: [], strategy_version: "v1", created_at: "2026-07-15T10:30:00+08:00",
    };
    const foreign = { ...selected, advice_id: "foreign", symbol: "000001", conclusion: "平安建议" };
    const bond = { ...selected, advice_id: "bond", asset: "convertible_bond" as const, conclusion: "转债建议" };
    const slot = { ...emptySlot, phase_status: "ready" as const, quality: "ready" as const, aggregate_version: "s1", ai_status: "not_requested" as const, advice: [selected, foreign, bond], change_stream: [{ snapshot_id: "s1", sequence: 1, generated_at: selected.created_at, delta_advice: [selected, foreign, bond], delta_plans: [] }] };
    render(<DecisionWorkbench selectedSymbol="600000" loadCurrent={() => Promise.resolve(response({ phases: { premarket: emptySlot, intraday: slot, postclose: emptySlot } }))} />);
    expect(await screen.findByText(/600000 · 等待 · 浦发等待/)).toBeInTheDocument();
    expect(screen.queryByText(/000001|平安建议|转债建议/)).not.toBeInTheDocument();
  });

  it("stops polling in explicit history mode and resumes only after returning live", async () => {
    vi.useFakeTimers();
    try {
      const loadCurrent = vi.fn().mockResolvedValue(response());
      const loadDate = vi.fn().mockResolvedValue(response());
      render(<DecisionWorkbench loadCurrent={loadCurrent} loadDate={loadDate} />);
      await vi.runOnlyPendingTimersAsync();
      fireEvent.change(screen.getByLabelText("交易日期"), { target: { value: "2026-07-14" } });
      await vi.runOnlyPendingTimersAsync();
      const currentBeforeHistoryWait = loadCurrent.mock.calls.length;
      const historyBeforeWait = loadDate.mock.calls.length;
      await vi.advanceTimersByTimeAsync(60_000);
      expect(loadCurrent).toHaveBeenCalledTimes(currentBeforeHistoryWait);
      expect(loadDate).toHaveBeenCalledTimes(historyBeforeWait);

      fireEvent.click(screen.getByRole("button", { name: "返回实时" }));
      await vi.runOnlyPendingTimersAsync();
      const currentAfterReturn = loadCurrent.mock.calls.length;
      await vi.advanceTimersByTimeAsync(60_000);
      expect(loadCurrent.mock.calls.length).toBeGreaterThan(currentAfterReturn);
    } finally { vi.useRealTimers(); }
  });
});
