import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AShareResearchView } from "./AShareResearchView";
import { SelectedInstrumentProvider } from "../instrument-selection/SelectedInstrumentProvider";


const factor = {
  symbol: "600000", as_of: "2026-07-14", close: "10.25",
  return_5d: "0.05", return_20d: "0.12", distance_ma20: "0.03",
  volume_ratio_5_20: "1.4", volatility_20d: "0.02", drawdown_60d: "-0.04",
  liquidity_amount_20d: "50000000", factor_version: "a-share-factors-v1",
  source: "mootdx",
};

const boards = {
  asset: "a_share" as const, snapshot_id: "board-1", input_snapshot_hash: "a".repeat(64),
  universe_status: "ready" as const,
  as_of: "2026-07-14", factor_version: "a-share-factors-v1",
  short_term: [{
    symbol: "600000", horizon: "short_term" as const, score: "68.5",
    score_breakdown: { momentum: "30", volume: "20", trend: "12", liquidity: "8", risk_penalty: "-1.5" },
    factor_snapshot: factor,
  }],
  swing: [{
    symbol: "000001", horizon: "swing" as const, score: "61.0",
    score_breakdown: { momentum: "20", trend: "24", liquidity: "9", volatility_penalty: "-2", drawdown_penalty: "-1" },
    factor_snapshot: { ...factor, symbol: "000001" },
  }],
  exclusions: [],
};

const readySection = (source = "mootdx") => ({
  status: "ready" as const, observed_at: "2026-07-14", source,
  metrics: {}, evidence_ids: [], explanation: "数据已冻结并完成校验。",
});

const partialDiagnosis = {
  asset: "a_share" as const, snapshot_id: "diagnosis-1",
  input_snapshot_hash: "b".repeat(64), symbol: "600000", as_of: "2026-07-14",
  action: "observe" as const, overall_status: "partial" as const,
  factor_version: "a-share-factors-v1", missing_data: ["fundamentals"],
  sections: {
    market: { ...readySection("tencent"), metrics: { name: "浦发银行", price: "10.25", change_percent: "1.49" } },
    price_volume: { ...readySection(), metrics: { close: "10.25", volume_ratio: "1.4" } },
    trend: { ...readySection(), metrics: { distance_ma20: "0.03", return_20d: "0.12" } },
    valuation: { ...readySection("tencent"), metrics: { pe_ttm: "6.32", pb: "0.58" } },
    fundamentals: { status: "unavailable" as const, observed_at: null, source: "mootdx-finance", metrics: {}, evidence_ids: [], explanation: "基本面数据不可用：未授权" },
    events: { ...readySection("frozen-news-events"), metrics: { event_count: 0, adverse_event_count: 0, event_industries: "" }, evidence_ids: ["event-verified-news-1"] },
    industry: { ...readySection("eastmoney-stock-classification"), metrics: { industry: "银行", board_tags: "银行" }, evidence_ids: ["stock-classification-1234567890abcdef12345678"] },
    risk: { ...readySection("qibao-risk-v1"), metrics: { missing_section_count: 1 } },
  },
};

describe("AShareResearchView", () => {
  it("loads URL selection and writes candidate selection back to global state", async () => {
    window.history.replaceState({}, "", "/a-shares?symbol=600000");
    const loadDiagnosis = vi.fn(() => Promise.resolve(partialDiagnosis));
    render(<SelectedInstrumentProvider><AShareResearchView loadCandidates={() => Promise.resolve(boards)} loadDiagnosis={loadDiagnosis} /></SelectedInstrumentProvider>);
    expect(await screen.findByRole("heading", { name: /浦发银行.*600000/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "波段榜" }));
    fireEvent.click(screen.getByRole("button", { name: /000001/ }));
    expect(new URL(window.location.href).searchParams.get("symbol")).toBe("000001");
    await waitFor(() => expect(loadDiagnosis).toHaveBeenLastCalledWith("000001", "2026-07-14"));
  });
  it("keeps short-term and swing candidates separate", async () => {
    render(<AShareResearchView
      loadCandidates={() => Promise.resolve(boards)}
      loadDiagnosis={() => Promise.resolve(partialDiagnosis)}
    />);

    expect(await screen.findByRole("button", { name: /600000/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /000001/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "波段榜" }));
    expect(screen.getByRole("button", { name: /000001/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /600000/ })).not.toBeInTheDocument();
  });

  it("keeps trend evidence visible when fundamentals are unavailable", async () => {
    const loadDiagnosis = vi.fn(() => Promise.resolve(partialDiagnosis));
    render(<AShareResearchView
      loadCandidates={() => Promise.resolve(boards)} loadDiagnosis={loadDiagnosis}
    />);

    fireEvent.click(await screen.findByRole("button", { name: /600000/ }));

    expect(await screen.findByText("基本面数据暂不可用")).toBeInTheDocument();
    expect(screen.getByText("MA20 趋势偏离")).toBeInTheDocument();
    expect(screen.getAllByText(/数据截至/).length).toBeGreaterThan(0);
    expect(loadDiagnosis).toHaveBeenCalledWith("600000", "2026-07-14");
  });

  it("shows the exact immutable evidence ids under their own sources", async () => {
    render(<AShareResearchView
      loadCandidates={() => Promise.resolve(boards)}
      loadDiagnosis={() => Promise.resolve(partialDiagnosis)}
    />);

    fireEvent.click(await screen.findByRole("button", { name: /600000/ }));
    const industrySection = (await screen.findByText("行业归属")).closest("section");
    const newsSection = screen.getByText("关联事件").closest("section");
    expect(industrySection).not.toBeNull();
    expect(newsSection).not.toBeNull();
    fireEvent.click(within(industrySection!).getByText("1 条冻结证据"));
    fireEvent.click(within(newsSection!).getByText("1 条冻结证据"));
    expect(within(industrySection!).getByText(
      "stock-classification-1234567890abcdef12345678",
    )).toBeInTheDocument();
    expect(within(newsSection!).getByText("event-verified-news-1")).toBeInTheDocument();
    expect(within(industrySection!).queryByText("event-verified-news-1")).not.toBeInTheDocument();
  });

  it("explains an empty local universe without inventing candidates", async () => {
    render(<AShareResearchView
      loadCandidates={() => Promise.resolve({ ...boards, universe_status: "empty", short_term: [], swing: [] })}
      loadDiagnosis={() => Promise.resolve(partialDiagnosis)}
    />);

    expect(await screen.findByText("本地候选池为空")).toBeInTheDocument();
    expect(screen.getByText(/先到工部同步/)).toBeInTheDocument();
  });

  it("uses a neutral message when only the selected ranking is empty", async () => {
    render(<AShareResearchView
      loadCandidates={() => Promise.resolve({ ...boards, short_term: [] })}
      loadDiagnosis={() => Promise.resolve(partialDiagnosis)}
    />);

    expect(await screen.findByText("当前榜单暂无候选")).toBeInTheDocument();
    expect(screen.queryByText(/先到工部同步/)).not.toBeInTheDocument();
  });

  it("returns diagnosis to the explicit idle state when switching rankings", async () => {
    render(<AShareResearchView
      loadCandidates={() => Promise.resolve(boards)}
      loadDiagnosis={() => Promise.resolve(partialDiagnosis)}
    />);

    fireEvent.click(await screen.findByRole("button", { name: /600000/ }));
    expect(await screen.findByText("基本面数据暂不可用")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "波段榜" }));
    expect(screen.getByText("选择候选标的")).toBeInTheDocument();
  });

  it("ignores a stale diagnosis response after the selected ranking changes", async () => {
    let resolveDiagnosis!: (value: typeof partialDiagnosis) => void;
    const pending = new Promise<typeof partialDiagnosis>((resolve) => { resolveDiagnosis = resolve; });
    render(<AShareResearchView
      loadCandidates={() => Promise.resolve(boards)}
      loadDiagnosis={() => pending}
    />);

    fireEvent.click(await screen.findByRole("button", { name: /600000/ }));
    fireEvent.click(screen.getByRole("tab", { name: "波段榜" }));
    resolveDiagnosis(partialDiagnosis);

    await waitFor(() => expect(screen.getByText("选择候选标的")).toBeInTheDocument());
    expect(screen.queryByText("浦发银行 · 600000")).not.toBeInTheDocument();
  });

  it("links tabs to a panel and supports arrow-key navigation", async () => {
    render(<AShareResearchView
      loadCandidates={() => Promise.resolve(boards)}
      loadDiagnosis={() => Promise.resolve(partialDiagnosis)}
    />);

    const shortTab = await screen.findByRole("tab", { name: "短线榜" });
    const swingTab = screen.getByRole("tab", { name: "波段榜" });
    expect(shortTab).toHaveAttribute("aria-controls", "a-share-candidate-panel");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "a-share-short-term-tab");
    shortTab.focus();
    fireEvent.keyDown(shortTab, { key: "ArrowRight" });
    expect(swingTab).toHaveFocus();
    expect(swingTab).toHaveAttribute("aria-selected", "true");
  });

  it("surfaces candidate request failures", async () => {
    render(<AShareResearchView
      loadCandidates={() => Promise.reject(new Error("候选数据仓暂不可用"))}
      loadDiagnosis={() => Promise.resolve(partialDiagnosis)}
    />);

    expect(await screen.findByRole("alert")).toHaveTextContent("候选数据仓暂不可用");
  });
});
