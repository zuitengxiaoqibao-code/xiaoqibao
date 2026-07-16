import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Advice, DecisionResponse } from "../decision-workbench/types";
import { HistoryReview } from "./HistoryReview";

const advice: Advice = { advice_id: "hidden", snapshot_id: "hidden-snapshot", asset: "a_share", symbol: "600000", horizon: "intraday", observation_state: "watching", action: "observe", conclusion: "保持关注", confidence: "0.7", supporting_evidence: [{ evidence_id: "e1", source: "tencent", snapshot_id: "s1", summary: "量价平稳", observed_at: "2026-07-15T10:00:00+08:00" }], contrary_evidence: [], risks: ["市场波动"], invalidation_conditions: [], plain_language_explanation: "继续观察", quantitative_result: {}, ai_interpretation_id: null, strategy_version: "hidden-version", created_at: "2026-07-15T10:01:00+08:00", risk_decision_id: null, previous_advice_id: null, changed_fields: [] };
const response = (date = "2026-07-15"): DecisionResponse => ({ server_time: "2026-07-15T10:02:00+08:00", trading_date: date, current_phase: "intraday", market_session: "open", polling: { focus_interval_seconds: 60, universe_interval_seconds: 60, stale_after_seconds: 180, next_check_seconds: 60 }, phases: { premarket: { phase_status: "empty", quality: "empty", aggregate_version: null, ai_status: "not_requested", advice: [], evidence: [] }, intraday: { phase_status: "ready", quality: "ready", aggregate_version: "hidden", ai_status: "ready", advice: [advice], evidence: [] }, postclose: { phase_status: "empty", quality: "empty", aggregate_version: null, ai_status: "not_requested", advice: [], evidence: [] } } });

describe("HistoryReview", () => {
  it("shows only beginner review information", async () => {
    render(<HistoryReview loadCurrent={() => Promise.resolve(response())} loadDate={() => Promise.resolve(response())} symbol="600000" />);
    expect(await screen.findByText("保持关注")).toBeInTheDocument();
    expect(screen.getByText("量价平稳")).toBeInTheDocument();
    expect(screen.getByText("市场波动")).toBeInTheDocument();
    expect(screen.queryByText(/hidden|snapshot|version|轮询|聚合|差异/)).not.toBeInTheDocument();
  });
  it("loads the selected historical date", async () => {
    const loadDate = vi.fn(() => Promise.resolve(response("2026-07-14")));
    render(<HistoryReview loadCurrent={() => Promise.resolve(response())} loadDate={loadDate} symbol="600000" />);
    fireEvent.change(screen.getByLabelText("复盘日期"), { target: { value: "2026-07-14" } });
    expect(await screen.findByText(/2026-07-14/)).toBeInTheDocument();
    expect(loadDate).toHaveBeenCalledWith("2026-07-14");
  });
  it("distinguishes a phase that excluded the stock from a phase with no output", async () => {
    const data = response();
    data.phases.intraday.advice = [];
    render(<HistoryReview loadCurrent={() => Promise.resolve(data)} symbol="600000" />);

    expect(await screen.findByText("本阶段已运行，当时未纳入这只股票")).toBeInTheDocument();
    expect(screen.getAllByText("本阶段没有生成可核验记录")).toHaveLength(2);
  });
});
