import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PhaseTimeline } from "./PhaseTimeline";
import type { StockCockpitSnapshot } from "./types";

describe("PhaseTimeline", () => {
  it("shows only the selected stock and the complete three-phase lineage", () => {
    const item = { advice_id: "a1", snapshot_id: "s1", symbol: "600000", horizon: "intraday" as const, action: "wait" as const, conclusion: "等待确认", confidence: "0.5", supporting_evidence: [], contrary_evidence: [], risks: ["波动"], invalidation_conditions: ["条件变化"], strategy_version: "v1", created_at: "2026-07-15T10:30:00+08:00", previous_advice_id: "a0", changed_fields: ["conclusion"] };
    const foreign = { ...item, advice_id: "a2", symbol: "000001" };
    const phases: StockCockpitSnapshot["phases"] = {
      premarket: { advice: [item, foreign], change_stream: [{ snapshot_id: "s1", sequence: 1, generated_at: item.created_at, status: "ready" }] },
      intraday: { advice: [], change_stream: [] }, postclose: { advice: [], change_stream: [] },
    };
    render(<PhaseTimeline phases={phases} symbol="600000" />);
    expect(screen.getByText("盘前研判")).toBeInTheDocument();
    expect(screen.getByText("盘中变化")).toBeInTheDocument();
    expect(screen.getByText("盘后验证")).toBeInTheDocument();
    expect(screen.queryByText("000001")).not.toBeInTheDocument();
    expect(screen.getByText(/前序建议：a0/)).toBeInTheDocument();
    expect(screen.getAllByText("该股票暂无已验证记录")).toHaveLength(2);
  });
});
