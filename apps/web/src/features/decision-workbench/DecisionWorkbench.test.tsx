import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DecisionWorkbench } from "./DecisionWorkbench";
import type { DecisionResponse } from "./types";

const emptySlot = { phase_status: "empty" as const, quality: "empty" as const, aggregate_version: null, ai_status: "not_requested" as const, advice: [], evidence: [], plans: [] };

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
      advice_id: "a1", snapshot_id: "s1", symbol: "600000", horizon: "swing" as const,
      action: "simulated_plan" as const, conclusion: "仅用于模拟观察", confidence: "0.72",
      supporting_evidence: [{ evidence_id: "e1", source: "tencent", snapshot_id: "q1", summary: "价格快照有效", observed_at: "2026-07-15T10:29:00+08:00" }],
      contrary_evidence: [], risks: ["市场波动"], invalidation_conditions: ["跌破观察区间"],
      plain_language_explanation: "条件满足后也只进入模拟计划。", strategy_version: "strategy-v1", created_at: "2026-07-15T10:30:00+08:00",
      simulation_plan_id: "p1", risk_decision_id: "r1",
    };
    const plan = { plan_id: "p1", advice_id: "a1", risk_decision_id: "r1", compliance_snapshot_id: "c1", watch_price_low: "10", watch_price_high: "10.2", stop_loss: "9.8", take_profit: ["10.6"], tranches: ["0.2"], max_position: "0.2", invalidation_conditions: ["跌破观察区间"], strategy_version: "strategy-v1", risk_version: "risk-v1", compliance_version: "compliance-v1" };
    const intraday = { ...emptySlot, phase_status: "ready" as const, quality: "ready" as const, aggregate_version: "s1", ai_status: "ready" as const, advice: [advice], plans: [plan] };
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
});
