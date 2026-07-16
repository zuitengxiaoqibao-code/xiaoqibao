import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SelectedInstrumentProvider } from "../instrument-selection/SelectedInstrumentProvider";
import type { Advice } from "../decision-workbench/types";
import { StockDecisionCockpit } from "./StockDecisionCockpit";
import type { CockpitSection, StockCockpitSnapshot } from "./types";

const observedAt = "2026-07-15T10:29:00+08:00";

function advice(overrides: Partial<Advice> = {}): Advice {
  return {
    advice_id: "a1", snapshot_id: "s1", asset: "a_share", symbol: "600000",
    horizon: "intraday", observation_state: "watching", action: "observe",
    conclusion: "保持观察", confidence: "0.72",
    supporting_evidence: [{ evidence_id: "e1", source: "tencent", snapshot_id: "q1", summary: "量价稳定", observed_at: observedAt }],
    contrary_evidence: [], risks: ["市场波动"], invalidation_conditions: ["趋势改变"],
    plain_language_explanation: "等待更多确认", quantitative_result: {}, ai_interpretation_id: null,
    risk_decision_id: null, previous_advice_id: null, changed_fields: [],
    strategy_version: "v1", created_at: "2026-07-15T10:30:00+08:00", ...overrides,
  };
}

function section(name: string): CockpitSection {
  return { status: "ready", source: `fixture-${name}`, observed_at: observedAt, snapshot_id: `snapshot-${name}`, reason: null, payload: { metrics: name === "market" ? { latest_price: "10.25", change_percent: "1.49" } : {} } };
}

function snapshot(overrides: Partial<StockCockpitSnapshot> = {}): StockCockpitSnapshot {
  const item = advice();
  const sections = Object.fromEntries(["market", "price_volume", "trend", "valuation", "fundamentals", "funds", "news", "industry", "risk", "backtest"].map((name) => [name, section(name)]));
  return {
    symbol: "600000", as_of: "2026-07-15", cutoff: "2026-07-15T10:30:00+08:00", overall_quality: "ready",
    instrument: { symbol: "600000", name: "浦发银行", exchange: "sh", observed_at: observedAt, quote_quality: "ready" },
    preparation: { symbol: "600000", status: "ready", refreshed: true, started_at: observedAt, completed_at: observedAt, sources: [
      { name: "quote", status: "ready", observed_at: observedAt, reason: null },
      { name: "history", status: "ready", observed_at: observedAt, reason: null },
      { name: "finance", status: "partial", observed_at: null, reason: "source unavailable" },
      { name: "news", status: "ready", observed_at: observedAt, reason: null },
    ] },
    candidate_membership: ["short_term"],
    assessment: { assessment_id: "assessment-1", symbol: "600000", action: "observe", conclusion: "行情与趋势可用，保持观察。", confidence: "0.75", supporting_evidence: item.supporting_evidence, contrary_evidence: [], risks: ["市场波动"], invalidation_conditions: ["趋势改变"], generated_at: "2026-07-15T10:30:00+08:00" },
    ai_status: "unconfigured", ai_explanation: null, current_advice: [item], sections,
    phases: { premarket: { advice: [], change_stream: [] }, intraday: { advice: [item], change_stream: [] }, postclose: { advice: [], change_stream: [] } },
    ...overrides,
  };
}

function renderCockpit(load: (symbol: string, asOf?: string, signal?: AbortSignal) => Promise<StockCockpitSnapshot>, asOf?: string) {
  window.history.replaceState({}, "", "/?symbol=600000");
  return render(<SelectedInstrumentProvider><StockDecisionCockpit load={load} asOf={asOf} /></SelectedInstrumentProvider>);
}

describe("StockDecisionCockpit", () => {
  it("renders a beginner action card and hides internal decision machinery", async () => {
    renderCockpit(() => Promise.resolve(snapshot()));
    expect(await screen.findByText("行情与趋势可用，保持观察。")).toBeInTheDocument();
    expect(screen.getAllByText("加入观察").length).toBeGreaterThan(0);
    expect(screen.getByText("需要等待的信号")).toBeInTheDocument();
    expect(screen.getByText("重新判断条件")).toBeInTheDocument();
    expect(screen.getByText("数据详情")).toBeInTheDocument();
    expect(screen.queryByText("资金数据尚未接入")).not.toBeInTheDocument();
    expect(screen.queryByText("尚未为该股票运行回测")).not.toBeInTheDocument();
    expect(screen.queryByText(/模拟操作|候选账本|策略：|研判编号|中书省|工部/)).not.toBeInTheDocument();
  });

  it("keeps the last snapshot visible and marks it stale after refresh failure", async () => {
    const load = vi.fn().mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error("offline"));
    renderCockpit(load);
    await screen.findByText("浦发银行");
    fireEvent.click(screen.getByRole("button", { name: "刷新驾驶舱" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("股票分析暂不可用，请稍后重试。");
    expect(screen.queryByText("offline")).not.toBeInTheDocument();
    expect(screen.getByText("当前内容已陈旧")).toBeInTheDocument();
    expect(screen.getByText("浦发银行")).toBeInTheDocument();
  });

  it("keeps the action card available when an older API snapshot has no preparation report", async () => {
    renderCockpit(() => Promise.resolve(snapshot({ preparation: undefined })));
    expect((await screen.findAllByText("加入观察")).length).toBeGreaterThan(0);
    expect(screen.getByText("已根据当前数据分区检查可用性")).toBeInTheDocument();
  });

  it("never exposes hostile raw keys, JSON, reason codes, or source identifiers", async () => {
    const hostile = snapshot();
    hostile.sections.market = { status: "partial", source: "internal_secret_feed", observed_at: observedAt, snapshot_id: "hidden", reason: "SECRET_REASON_CODE", payload: { explanation: "工部 internal-id-999", metrics: { latest_price: "10", secret_alpha: "LEAK", nested: { token: "LEAK_JSON" } } } };
    renderCockpit(() => Promise.resolve(hostile));
    await screen.findByText("数据详情");
    fireEvent.click(screen.getByText("数据详情"));
    expect(screen.getByText("未提供可展示说明")).toBeInTheDocument();
    expect(screen.queryByText(/SECRET|internal_secret|secret_alpha|LEAK|\{"token"|工部|internal-id/)).not.toBeInTheDocument();
  });

  it("does not retain live data when a historical request fails", async () => {
    const load = vi.fn().mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error("history unavailable"));
    const view = renderCockpit(load);
    await screen.findByText("浦发银行");
    view.rerender(<SelectedInstrumentProvider><StockDecisionCockpit load={load} asOf="2026-07-14" /></SelectedInstrumentProvider>);
    expect(await screen.findByText("驾驶舱暂不可用")).toBeInTheDocument();
    expect(screen.queryByText("浦发银行")).not.toBeInTheDocument();
  });

  it("prevents an older stock response from replacing a newer selection", async () => {
    let resolveOld!: (value: StockCockpitSnapshot) => void;
    const load = vi.fn((symbol: string) => symbol === "600000"
      ? new Promise<StockCockpitSnapshot>((resolve) => { resolveOld = resolve; })
      : Promise.resolve(snapshot({ symbol: "000001", instrument: { ...snapshot().instrument, symbol: "000001", name: "平安银行" } })));
    renderCockpit(load);
    await act(async () => {
      window.history.pushState({}, "", "/?symbol=000001");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(await screen.findByText("平安银行")).toBeInTheDocument();
    await act(async () => resolveOld(snapshot()));
    expect(screen.queryByText("浦发银行")).not.toBeInTheDocument();
  });
});
