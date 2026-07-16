import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Dashboard } from "./Dashboard";
import { SelectedInstrumentProvider } from "../instrument-selection/SelectedInstrumentProvider";

const freshCard = {
  symbol: "600000",
  asset: "a_share" as const,
  action: "observe" as const,
  change_percent: "1.49",
  quality: "fresh" as const,
  invalid_reasons: [],
  evidence: [
    {
      label: "最新价",
      value: "10.25",
      source: "tencent",
      observed_at: "2026-07-13T10:30:00",
    },
  ],
};

const coordinatedDecision = {
  server_time: "2026-07-15T10:30:00+08:00", trading_date: "2026-07-15", current_phase: "intraday" as const, market_session: "open" as const,
  phases: {
    premarket: { phase_status: "empty" as const, quality: "empty" as const, aggregate_version: null, ai_status: "not_requested" as const, advice: [], evidence: [], plans: [], plan_readiness: {} },
    intraday: { phase_status: "empty" as const, quality: "empty" as const, aggregate_version: null, ai_status: "not_requested" as const, advice: [], evidence: [], plans: [], plan_readiness: {} },
    postclose: { phase_status: "empty" as const, quality: "empty" as const, aggregate_version: null, ai_status: "not_requested" as const, advice: [], evidence: [], plans: [], plan_readiness: {} },
  }, polling: { focus_interval_seconds: 60, universe_interval_seconds: 240, stale_after_seconds: 180, next_check_seconds: 60 },
};

describe("Dashboard", () => {
  it("keeps the authoritative three-phase workbench mounted with the single-stock cockpit", async () => {
    window.history.replaceState({}, "", "/");
    render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(freshCard)}
      loadDecisionCurrent={() => new Promise(() => undefined)}
      loadStockCockpit={() => new Promise(() => undefined)}
    /></SelectedInstrumentProvider>);
    expect(screen.getByRole("heading", { name: "先选择一只 A 股" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "今日判断与三阶段跟踪" })).toBeInTheDocument();
    expect(screen.queryByText("模拟交易与资金台账")).not.toBeInTheDocument();
    expect(screen.queryByText("模拟资金")).not.toBeInTheDocument();
  });

  it("does not expose the removed paper trading panel", () => {
    window.history.replaceState({}, "", "/");
    const { container } = render(<SelectedInstrumentProvider><Dashboard
      loadSnapshot={() => Promise.resolve(freshCard)}
    /></SelectedInstrumentProvider>);

    expect(container.querySelector(".paper-panel")).not.toBeInTheDocument();
  });

  it("drives cockpit and workbench from the same historical date", async () => {
    window.history.replaceState({}, "", "/?symbol=600000");
    const loadDate = vi.fn().mockResolvedValue(coordinatedDecision);
    const loadCockpit = vi.fn(() => new Promise<never>(() => undefined));
    render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(freshCard)} loadDecisionCurrent={() => Promise.resolve(coordinatedDecision)} loadDecisionDate={loadDate} loadStockCockpit={loadCockpit} /></SelectedInstrumentProvider>);
    await screen.findByRole("tab", { name: "盘中监测" });
    fireEvent.change(screen.getByLabelText("交易日期"), { target: { value: "2026-07-14" } });
    expect(loadDate).toHaveBeenCalledWith("2026-07-14");
    expect(loadCockpit).toHaveBeenCalledWith("600000", "2026-07-14", expect.any(AbortSignal));
  });

  it("loads the live cockpit only once while the current trading date initializes", async () => {
    window.history.replaceState({}, "", "/?symbol=600000");
    const loadCockpit = vi.fn(() => new Promise<never>(() => undefined));
    render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(freshCard)} loadDecisionCurrent={() => Promise.resolve(coordinatedDecision)} loadStockCockpit={loadCockpit} /></SelectedInstrumentProvider>);
    await screen.findByRole("tab", { name: "盘中监测" });
    await act(async () => { await Promise.resolve(); });
    expect(loadCockpit).toHaveBeenCalledTimes(1);
    expect(loadCockpit).toHaveBeenCalledWith("600000", undefined, expect.any(AbortSignal));
  });

  it("uses the workbench polling clock to refresh both views", async () => {
    vi.useFakeTimers();
    try {
      window.history.replaceState({}, "", "/?symbol=600000");
      const loadCurrent = vi.fn().mockResolvedValue(coordinatedDecision);
      const loadCockpit = vi.fn(() => new Promise<never>(() => undefined));
      render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(freshCard)} loadDecisionCurrent={loadCurrent} loadStockCockpit={loadCockpit} /></SelectedInstrumentProvider>);
      await act(async () => { await loadCurrent.mock.results[0].value; });
      const cockpitBefore = loadCockpit.mock.calls.length;
      await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
      expect(loadCurrent.mock.calls.length).toBeGreaterThan(1);
      expect(loadCockpit.mock.calls.length).toBeGreaterThan(cockpitBefore);
    } finally { vi.useRealTimers(); }
  });

  it("refreshes cockpit and workbench together from the shared refresh command", async () => {
    window.history.replaceState({}, "", "/?symbol=600000");
    const loadCurrent = vi.fn().mockResolvedValue(coordinatedDecision);
    const loadCockpit = vi.fn(() => new Promise<never>(() => undefined));
    render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(freshCard)} loadDecisionCurrent={loadCurrent} loadStockCockpit={loadCockpit} /></SelectedInstrumentProvider>);
    await screen.findByRole("tab", { name: "盘中监测" });
    const cockpitBefore = loadCockpit.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "刷新当前" }));
    await vi.waitFor(() => expect(loadCurrent.mock.calls.length).toBeGreaterThan(1));
    expect(loadCockpit.mock.calls.length).toBeGreaterThan(cockpitBefore);
  });
  it("keeps the three-phase workbench beside an empty candidate selector without guessing", async () => {
    window.history.replaceState({}, "", "/");
    render(<SelectedInstrumentProvider><Dashboard
      loadSnapshot={() => Promise.resolve(freshCard)}
      loadDecisionCurrent={() => new Promise(() => undefined)}
      loadAShareCandidates={() => Promise.resolve({
        asset: "a_share", snapshot_id: null, input_snapshot_hash: null,
        universe_status: "empty", as_of: "2026-07-15", factor_version: "a-share-factors-v1",
        short_term: [], swing: [], exclusions: [],
      })}
      searchAShareInstruments={() => Promise.resolve({ query: "", items: [], server_time: "2026-07-15T09:30:00+08:00", source_status: "ready" })}
    /></SelectedInstrumentProvider>);

    expect(await screen.findByText("本地候选池为空")).toBeInTheDocument();
    expect(screen.getByText("尚未选择 A 股")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "今日判断与三阶段跟踪" })).toBeInTheDocument();
    expect(new URL(window.location.href).searchParams.has("symbol")).toBe(false);
  });

  it("opens the independent A-share research workspace", async () => {
    window.history.replaceState({}, "", "/");
    render(<Dashboard
      loadSnapshot={() => Promise.resolve(freshCard)}
      loadAShareCandidates={() => Promise.resolve({
        asset: "a_share", snapshot_id: null, input_snapshot_hash: null,
        universe_status: "empty",
        as_of: "2026-07-14", factor_version: "a-share-factors-v1",
        short_term: [], swing: [], exclusions: [],
      })}
      loadAShareDiagnosis={() => Promise.reject(new Error("unused"))}
    />);

    fireEvent.click(screen.getByRole("button", { name: /A 股主域/ }));

    expect(await screen.findByRole("heading", { name: "A 股研究工作区" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/a-shares");
  });

  it("restores the A-share research deep link", async () => {
    window.history.replaceState({}, "", "/a-shares");
    render(<Dashboard
      loadSnapshot={() => Promise.resolve(freshCard)}
      loadAShareCandidates={() => Promise.resolve({
        asset: "a_share", snapshot_id: null, input_snapshot_hash: null,
        universe_status: "empty",
        as_of: "2026-07-14", factor_version: "a-share-factors-v1",
        short_term: [], swing: [], exclusions: [],
      })}
      loadAShareDiagnosis={() => Promise.reject(new Error("unused"))}
    />);

    expect(await screen.findByRole("heading", { name: "A 股研究工作区" })).toBeInTheDocument();
  });

  it("navigates to the news intelligence deep link", async () => {
    window.history.replaceState({}, "", "/?symbol=600000");
    render(<SelectedInstrumentProvider><Dashboard
      loadSnapshot={() => Promise.resolve(freshCard)}
      loadNewsIntelligence={() => Promise.resolve({
        events: [], interpretations: [], corrections: [], briefings: [],
        quality: { article_count: 0, cluster_count: 0, event_count: 0, interpretation_count: 0, correction_count: 0, citation_coverage: "1", duplicate_rate: "0", invalid_json_rate: "0", provider_error_rate: "0", human_correction_rate: "0" },
      })}
      syncNews={() => Promise.resolve({ fetched: 0 })}
      createNewsCorrection={() => Promise.resolve()}
    /></SelectedInstrumentProvider>);

    fireEvent.click(screen.getByRole("button", { name: /中书省/ }));

    expect(await screen.findByRole("heading", { name: "每日情报流" })).toBeInTheDocument();
    expect(screen.getByText("当前标的 600000")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/news-intelligence");
    expect(new URL(window.location.href).searchParams.get("symbol")).toBe("600000");
  });

  it("inherits the selected A-share in risk and backtest workspaces", async () => {
    window.history.replaceState({}, "", "/?symbol=600000");
    render(<SelectedInstrumentProvider><Dashboard
      loadSnapshot={() => Promise.resolve(freshCard)}
      loadRisk={() => Promise.resolve({ rule_version: "v1", limits: {}, recent_rejections: [] })}
      runBacktest={() => Promise.resolve({} as never)}
    /></SelectedInstrumentProvider>);

    fireEvent.click(screen.getByRole("button", { name: /刑部/ }));
    expect(await screen.findByText(/全局.*资产级治理数据/)).toBeInTheDocument();
    expect(screen.getByText(/导航代码 600000/)).toBeInTheDocument();
    expect(window.location.pathname).toBe("/risk");
    fireEvent.click(screen.getByRole("button", { name: /历史回测/ }));
    expect(await screen.findByRole("textbox", { name: "回测 A 股代码" })).toHaveValue("600000");
    expect(window.location.pathname).toBe("/backtest");
    expect(new URL(window.location.href).searchParams.get("symbol")).toBe("600000");
  });

  it("navigates to the independent convertible-bond domain", async () => {
    window.history.replaceState({}, "", "/?symbol=600000");
    render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(freshCard)}
      loadBondDashboard={() => Promise.resolve({ status: "empty", bond_count: 0, bond_codes: [] })}
      loadBondDiagnosis={() => Promise.reject(new Error("unused"))}
      loadBondCandidates={() => Promise.resolve({ status: "empty", items: [] })} /></SelectedInstrumentProvider>);

    fireEvent.click(screen.getByRole("button", { name: /可转债专区/ }));

    expect(await screen.findByRole("heading", { name: "可转债专区" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "今日情报态势" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "候选池" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/convertible-bonds");
    expect(new URL(window.location.href).searchParams.has("symbol")).toBe(false);
  });

  it("does not present an A-share navigation symbol as convertible-bond governance scope", async () => {
    window.history.replaceState({}, "", "/?symbol=600000");
    render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(freshCard)}
      loadBondDashboard={() => Promise.resolve({ status: "empty", bond_count: 0, bond_codes: [] })}
      loadBondDiagnosis={() => Promise.reject(new Error("unused"))}
      loadBondCandidates={() => Promise.resolve({ status: "empty", items: [] })}
      loadCompliance={() => Promise.resolve({ policy_state: "current", sources: [], features: [] })} /></SelectedInstrumentProvider>);
    fireEvent.click(screen.getByRole("button", { name: /可转债专区/ }));
    fireEvent.click(await screen.findByRole("button", { name: /礼部/ }));
    expect(await screen.findByText(/全局.*资产级治理数据/)).toBeInTheDocument();
    expect(screen.queryByText(/导航代码 600000/)).not.toBeInTheDocument();
  });

  it("restores A-share workspace selection across browser history", async () => {
    window.history.replaceState({}, "", "/news-intelligence?symbol=600000");
    render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(freshCard)}
      loadNewsIntelligence={() => Promise.resolve({ events: [], interpretations: [], corrections: [], briefings: [], quality: { article_count: 0, cluster_count: 0, event_count: 0, interpretation_count: 0, correction_count: 0, citation_coverage: "1", duplicate_rate: "0", invalid_json_rate: "0", provider_error_rate: "0", human_correction_rate: "0" } })}
      syncNews={() => Promise.resolve({ fetched: 0 })} createNewsCorrection={() => Promise.resolve()}
      runBacktest={() => Promise.resolve({} as never)} /></SelectedInstrumentProvider>);
    expect(await screen.findByText("当前标的 600000")).toBeInTheDocument();
    window.history.pushState({}, "", "/backtest?symbol=000001");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(await screen.findByRole("textbox", { name: "回测 A 股代码" })).toHaveValue("000001");
  });

  it("keeps a convertible-bond deep link after refresh and responds to popstate", async () => {
    window.history.replaceState({}, "", "/convertible-bonds");
    render(<Dashboard loadSnapshot={() => Promise.resolve(freshCard)}
      loadBondDashboard={() => Promise.resolve({ status: "empty", bond_count: 0, bond_codes: [] })}
      loadBondDiagnosis={() => Promise.reject(new Error("unused"))}
      loadBondCandidates={() => Promise.resolve({ status: "empty", items: [] })} />);
    expect(await screen.findByRole("heading", { name: "可转债专区" })).toBeInTheDocument();
    window.history.pushState({}, "", "/");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(await screen.findByRole("heading", { name: "今日情报态势" })).toBeInTheDocument();
  });

  it("shows evidence source and data time", async () => {
    render(<Dashboard loadSnapshot={() => Promise.resolve(freshCard)} />);

    fireEvent.click(screen.getByRole("button", { name: "调取行情" }));

    expect(await screen.findByText("腾讯行情")).toBeInTheDocument();
    expect(screen.getByText(/数据截至/)).toBeInTheDocument();
    expect(screen.getByText("600000")).toBeInTheDocument();
  });

  it("makes a blocked signal explicit", async () => {
    const blockedCard = {
      ...freshCard,
      action: "blocked" as const,
      quality: "stale" as const,
      invalid_reasons: ["数据已过期或质量异常"],
    };
    render(<Dashboard loadSnapshot={() => Promise.resolve(blockedCard)} />);

    fireEvent.click(screen.getByRole("button", { name: "调取行情" }));

    expect(await screen.findByRole("status")).toHaveTextContent("仅观察");
    expect(screen.getByText("数据已过期或质量异常")).toBeInTheDocument();
  });

  it("shows a loading state before the request completes", () => {
    render(<Dashboard loadSnapshot={() => new Promise(() => undefined)} />);

    fireEvent.click(screen.getByRole("button", { name: "调取行情" }));

    expect(screen.getByText("正在调取工部行情...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "调取行情" })).toBeDisabled();
  });

  it("surfaces network errors without inventing data", async () => {
    render(<Dashboard loadSnapshot={() => Promise.reject(new Error("行情源暂不可用"))} />);

    fireEvent.click(screen.getByRole("button", { name: "调取行情" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("行情源暂不可用");
  });

  it("passes the entered six-digit symbol to the API", async () => {
    const loadSnapshot = vi.fn(() => Promise.resolve(freshCard));
    render(<Dashboard loadSnapshot={loadSnapshot} />);

    fireEvent.change(screen.getByLabelText("A 股代码"), { target: { value: "000001" } });
    fireEvent.click(screen.getByRole("button", { name: "调取行情" }));

    await screen.findByText("腾讯行情");
    expect(loadSnapshot).toHaveBeenCalledWith("000001");
  });
});
