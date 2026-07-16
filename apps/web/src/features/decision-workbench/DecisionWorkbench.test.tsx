import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DecisionWorkbench } from "./DecisionWorkbench";
import type { Advice, DecisionResponse, PhaseSlot } from "./types";

const emptySlot: PhaseSlot = {
  phase_status: "empty", quality: "empty", aggregate_version: null,
  ai_status: "not_requested", advice: [], evidence: [],
};

function advice(overrides: Partial<Advice> = {}): Advice {
  return {
    advice_id: "a1", snapshot_id: "s1", asset: "a_share", symbol: "600000",
    horizon: "intraday", observation_state: "watching", action: "observe",
    conclusion: "保持观察", confidence: "0.7",
    supporting_evidence: [{ evidence_id: "e1", source: "tencent", snapshot_id: "q1", summary: "价格有效", observed_at: "2026-07-15T10:29:00+08:00" }],
    contrary_evidence: [], risks: ["波动"], invalidation_conditions: ["条件变化"],
    plain_language_explanation: null, quantitative_result: {}, ai_interpretation_id: null,
    risk_decision_id: null, previous_advice_id: null, changed_fields: [],
    strategy_version: "v1", created_at: "2026-07-15T10:30:00+08:00", ...overrides,
  };
}

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
  it("renders research advice and evidence without plan or gate fields", async () => {
    const item = advice();
    const slot: PhaseSlot = { ...emptySlot, phase_status: "ready", quality: "ready", aggregate_version: "s1", advice: [item], evidence: item.supporting_evidence };
    render(<DecisionWorkbench loadCurrent={() => Promise.resolve(response({ phases: { premarket: emptySlot, intraday: slot, postclose: emptySlot } }))} />);

    expect(await screen.findByText("600000 · 保持观察")).toBeInTheDocument();
    expect(screen.getByText("价格有效")).toBeInTheDocument();
    expect(screen.queryByText(/模拟操作计划|行情门禁|仓位/)).not.toBeInTheDocument();
  });

  it("explains that an empty premarket phase is scheduled rather than broken", async () => {
    const scheduled = {
      ...emptySlot,
      execution: {
        status: "scheduled", scheduled_at: "2026-07-17T09:20:00+08:00",
        next_scheduled_at: "2026-07-17T09:20:00+08:00", last_completed_at: null,
        last_attempt_at: null, attempts: 0, error_code: null,
      },
    } as PhaseSlot;
    render(<DecisionWorkbench loadCurrent={() => Promise.resolve(response({
      server_time: "2026-07-17T09:00:00+08:00", trading_date: "2026-07-17",
      current_phase: "premarket", market_session: "closed",
      phases: { premarket: scheduled, intraday: emptySlot, postclose: emptySlot },
    }))} />);

    expect(await screen.findByText("盘前研判计划 09:20 生成")).toBeInTheDocument();
    expect(screen.getByText("尚未到计划时间，不会提前编造结论。")).toBeInTheDocument();
  });

  it("keeps every phase lifecycle visible before the user switches tabs", async () => {
    const scheduled = {
      ...emptySlot,
      execution: {
        status: "scheduled", scheduled_at: "2026-07-17T09:20:00+08:00",
        next_scheduled_at: "2026-07-17T09:20:00+08:00", last_completed_at: null,
        last_attempt_at: null, attempts: 0, error_code: null,
      },
    } as PhaseSlot;
    const item = advice();
    const ready = {
      ...emptySlot, phase_status: "ready" as const, quality: "ready" as const,
      aggregate_version: "s1", advice: [item], evidence: item.supporting_evidence,
    };
    render(<DecisionWorkbench loadCurrent={() => Promise.resolve(response({
      server_time: "2026-07-17T10:30:00+08:00", trading_date: "2026-07-17",
      phases: { premarket: scheduled, intraday: ready, postclose: emptySlot },
    }))} />);

    expect(await screen.findByText("计划 09:20 生成")).toBeInTheDocument();
    expect(screen.getByText("已生成 1 条建议")).toBeInTheDocument();
    expect(screen.getByText("暂无已验证结果")).toBeInTheDocument();
  });

  it("loads explicit history and returns to the current endpoint", async () => {
    const loadCurrent = vi.fn().mockResolvedValue(response());
    const loadDate = vi.fn().mockResolvedValue(response({ trading_date: "2026-07-14", market_session: "closed" }));
    render(<DecisionWorkbench loadCurrent={loadCurrent} loadDate={loadDate} />);
    await screen.findByRole("tab", { name: "盘中监测" });

    fireEvent.change(screen.getByLabelText("交易日期"), { target: { value: "2026-07-14" } });
    expect(await screen.findByRole("button", { name: "返回实时" })).toBeInTheDocument();
    expect(loadDate).toHaveBeenCalledWith("2026-07-14");
    fireEvent.click(screen.getByRole("button", { name: "返回实时" }));
    expect(loadCurrent).toHaveBeenCalledTimes(2);
  });

  it("filters advice and change history to the selected A-share", async () => {
    const selected = advice();
    const foreign = advice({ advice_id: "a2", symbol: "000001", conclusion: "其他股票" });
    const slot: PhaseSlot = {
      ...emptySlot, phase_status: "ready", quality: "ready", aggregate_version: "s1",
      advice: [selected, foreign], evidence: [...selected.supporting_evidence, ...foreign.supporting_evidence],
      change_stream: [{ snapshot_id: "s1", sequence: 1, generated_at: selected.created_at, delta_advice: [selected, foreign] }],
    };
    render(<DecisionWorkbench selectedSymbol="600000" loadCurrent={() => Promise.resolve(response({ phases: { premarket: emptySlot, intraday: slot, postclose: emptySlot } }))} />);

    expect(await screen.findByText("600000 · 保持观察")).toBeInTheDocument();
    expect(screen.queryByText("其他股票")).not.toBeInTheDocument();
    expect(screen.getByText(/变化版本 #1/)).toBeInTheDocument();
  });

  it("ignores a stale historical response after a newer date wins", async () => {
    let resolveOld!: (value: DecisionResponse) => void;
    const old = new Promise<DecisionResponse>((resolve) => { resolveOld = resolve; });
    const loadDate = vi.fn((value: string) => value === "2026-07-14" ? old : Promise.resolve(response({ trading_date: value })));
    render(<DecisionWorkbench loadCurrent={() => Promise.resolve(response())} loadDate={loadDate} />);
    await screen.findByRole("tab", { name: "盘中监测" });
    fireEvent.change(screen.getByLabelText("交易日期"), { target: { value: "2026-07-14" } });
    fireEvent.change(screen.getByLabelText("交易日期"), { target: { value: "2026-07-13" } });
    await act(async () => resolveOld(response({ trading_date: "2026-07-14" })));
    expect((screen.getByLabelText("交易日期") as HTMLInputElement).value).toBe("2026-07-13");
  });
});
