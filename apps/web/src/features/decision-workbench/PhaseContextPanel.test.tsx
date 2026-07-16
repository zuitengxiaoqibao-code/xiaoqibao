import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PhaseContextPanel } from "./PhaseContextPanel";

describe("PhaseContextPanel", () => {
  it("shows verified market topics, industries and candidate fund flow", () => {
    render(<PhaseContextPanel context={{
      market_state: "strong", window_start: null, window_end: null,
      candidate_snapshot_id: "candidate-1", risk_event_count: 0, quality_reasons: [],
      market_overview: {
        summary: "候选因子宽度；已核验热点 1 个",
        hot_topics: ["人工智能"], industries: ["软件服务"],
        fund_flow: { inflow: 2, outflow: 1, available: 3 },
      },
      news: { status: "empty", events: [], missing_event_ids: [], error_code: null },
    }} />);

    expect(screen.getByText("人工智能")).toBeInTheDocument();
    expect(screen.getByText("软件服务")).toBeInTheDocument();
    expect(screen.getByText("流入 2 · 流出 1")).toBeInTheDocument();
  });
});
