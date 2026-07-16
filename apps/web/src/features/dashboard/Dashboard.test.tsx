import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SelectedInstrumentProvider } from "../instrument-selection/SelectedInstrumentProvider";
import { Dashboard, preparationForSymbol } from "./Dashboard";
import type { StockCockpitSnapshot } from "../stock-cockpit/types";

const card = {
  asset: "a_share" as const, symbol: "600000", action: "observe" as const, quality: "fresh" as const,
  change_percent: "1.2", invalid_reasons: [], evidence: [],
};

describe("Dashboard beginner shell", () => {
  beforeEach(() => window.history.replaceState({}, "", "/"));

  it("shows only the six plain-language navigation entries", () => {
    render(<Dashboard loadSnapshot={() => Promise.resolve(card)} />);
    const navigation = screen.getByRole("navigation", { name: "主要功能" });
    expect(navigation.querySelectorAll("button")).toHaveLength(6);
    expect(screen.getByRole("button", { name: "今日研判" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "数据设置" })).toBeInTheDocument();
    expect(screen.queryByText(/中书省|吏部|户部|东厂|礼部|兵部|尚书省|刑部|工部/)).not.toBeInTheDocument();
    expect(screen.queryByText(/模拟账户|模拟委托|模拟操作计划|API 密钥/)).not.toBeInTheDocument();
  });

  it("opens beginner risk and settings pages with stable routes", async () => {
    render(<Dashboard loadSnapshot={() => Promise.resolve(card)} loadRisk={() => Promise.resolve({ rule_version: "v1", limits: {} })} />);
    fireEvent.click(screen.getByRole("button", { name: "风险提醒" }));
    expect(await screen.findByRole("heading", { name: "当前风险状态" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/risk");
    fireEvent.click(screen.getByRole("button", { name: "数据设置" }));
    expect(screen.getByRole("heading", { name: "数据源与 AI" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings");
  });

  it("opens A-share observation without legacy research internals", async () => {
    render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(card)}
      loadAShareCandidates={() => Promise.resolve({ asset: "a_share", snapshot_id: null, input_snapshot_hash: null, universe_status: "empty", as_of: "2026-07-15", factor_version: "secret-factor", short_term: [], swing: [], exclusions: [] })}
      searchAShareInstruments={() => Promise.resolve({ query: "", items: [], server_time: "2026-07-15T09:30:00+08:00", source_status: "ready" })} /></SelectedInstrumentProvider>);
    fireEvent.click(screen.getByRole("button", { name: "A 股观察" }));
    expect(await screen.findByRole("heading", { name: "选择观察股票" })).toBeInTheDocument();
    expect(screen.queryByText(/secret-factor|snapshot|中书省|工部|候选生成|诊断/)).not.toBeInTheDocument();
  });

  it("keeps the selected A share while opening news", async () => {
    window.history.replaceState({}, "", "/?symbol=600000");
    render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(card)}
      loadNewsIntelligence={() => Promise.resolve({ events: [], interpretations: [], corrections: [], briefings: [], quality: { article_count: 0, cluster_count: 0, event_count: 0, interpretation_count: 0, correction_count: 0, citation_coverage: "1", duplicate_rate: "0", invalid_json_rate: "0", provider_error_rate: "0", human_correction_rate: "0" } })}
      syncNews={() => Promise.resolve({ fetched: 0 })} createNewsCorrection={() => Promise.resolve()} /></SelectedInstrumentProvider>);
    fireEvent.click(screen.getByRole("button", { name: "新闻热点" }));
    expect(await screen.findByText("当前标的 600000")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/news-intelligence");
    expect(new URL(window.location.href).searchParams.get("symbol")).toBe("600000");
  });

  it("keeps convertible bonds in an isolated route without the A-share symbol", async () => {
    window.history.replaceState({}, "", "/?symbol=600000");
    render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(card)}
      loadBondDashboard={() => Promise.resolve({ status: "empty", bond_count: 0, bond_codes: [] })}
      loadBondDiagnosis={() => Promise.reject(new Error("unused"))}
      loadBondCandidates={() => Promise.resolve({ status: "empty", items: [] })} /></SelectedInstrumentProvider>);
    fireEvent.click(screen.getByRole("button", { name: "可转债" }));
    expect(await screen.findByRole("heading", { name: "可转债专区" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/convertible-bonds");
    expect(new URL(window.location.href).searchParams.has("symbol")).toBe(false);
  });

  it("restores the last A-share selection after a bond round trip", async () => {
    window.history.replaceState({}, "", "/?symbol=600000");
    render(<SelectedInstrumentProvider><Dashboard loadSnapshot={() => Promise.resolve(card)}
      loadBondDashboard={() => Promise.resolve({ status: "empty", bond_count: 0, bond_codes: [] })}
      loadBondDiagnosis={() => Promise.reject(new Error("unused"))} loadBondCandidates={() => Promise.resolve({ status: "empty", items: [] })} /></SelectedInstrumentProvider>);
    fireEvent.click(screen.getByRole("button", { name: "可转债" }));
    expect(new URL(window.location.href).searchParams.has("symbol")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "今日研判" }));
    expect(new URL(window.location.href).searchParams.get("symbol")).toBe("600000");
  });

  it("restores a settings deep link", () => {
    window.history.replaceState({}, "", "/settings");
    render(<Dashboard loadSnapshot={vi.fn(() => Promise.resolve(card))} />);
    expect(screen.getByRole("heading", { name: "数据源与 AI" })).toBeInTheDocument();
  });

  it("does not pass an older stock preparation into settings for a new symbol", () => {
    const old = { symbol: "600000", preparation: { symbol: "600000", status: "ready", sources: [], refreshed: false, started_at: "2026-07-16T10:00:00+08:00", completed_at: "2026-07-16T10:00:01+08:00" } } as unknown as StockCockpitSnapshot;
    expect(preparationForSymbol(old, "000001")).toBeNull();
    expect(preparationForSymbol(old, "600000")?.symbol).toBe("600000");
  });
});
