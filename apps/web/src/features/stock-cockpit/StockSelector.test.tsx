import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SelectedInstrumentProvider } from "../instrument-selection/SelectedInstrumentProvider";
import type { CandidateBoard } from "../a-shares/types";
import { StockSelector } from "./StockSelector";
import type { InstrumentSearchResponse } from "./types";

const factor = {
  symbol: "600000", as_of: "2026-07-15", latest_trade_date: "2026-07-14",
  close: "10.25", return_5d: "0.0149",
  return_20d: "0.04", distance_ma20: "0.02", volume_ratio_5_20: "1.25",
  volatility_20d: "0.18", drawdown_60d: "-0.06", liquidity_amount_20d: "800000000",
  factor_version: "a-share-factors-v1", source: "local-daily-bars",
};
const first: CandidateBoard = {
  asset: "a_share", snapshot_id: "candidate-1", input_snapshot_hash: "a".repeat(64),
  universe_status: "ready", as_of: "2026-07-15", factor_version: "a-share-factors-v1",
  short_term: [{ symbol: "600000", horizon: "short_term", score: "68.5", score_breakdown: { momentum: "24.5", volume: "18" }, factor_snapshot: factor }],
  swing: [{ symbol: "000001", horizon: "swing", score: "61", score_breakdown: { trend: "22" }, factor_snapshot: { ...factor, symbol: "000001" } }], exclusions: [],
};
const empty: CandidateBoard = { ...first, universe_status: "empty", snapshot_id: null, short_term: [], swing: [] };
const searchResult: InstrumentSearchResponse = {
  query: "平安", source_status: "ready", server_time: "2026-07-15T09:30:00+08:00",
  items: [{ symbol: "000001", name: "平安银行", exchange: "sz", observed_at: "2026-07-15T09:29:00+08:00", quote_quality: "ready" }],
};
const puFaResult: InstrumentSearchResponse = {
  ...searchResult, query: "600000",
  items: [{ ...searchResult.items[0], symbol: "600000", name: "浦发银行", exchange: "sh" }],
};

function renderSelector(props: Partial<React.ComponentProps<typeof StockSelector>> = {}) {
  return render(<SelectedInstrumentProvider><StockSelector
    loadCandidates={() => Promise.resolve(first)} search={(query) => Promise.resolve(query === "600000" ? puFaResult : searchResult)} {...props}
  /></SelectedInstrumentProvider>);
}

describe("StockSelector", () => {
  beforeEach(() => { window.history.replaceState({}, "", "/"); localStorage.clear(); vi.useRealTimers(); });

  it("offers candidates and searches by code or name after 250ms", async () => {
    const search = vi.fn(() => Promise.resolve(searchResult));
    renderSelector({ search });
    expect(await screen.findByRole("button", { pressed: true })).toHaveTextContent("600000");
    const callsBeforeInput = search.mock.calls.length;
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索 A 股" }), { target: { value: "平安" } });
    expect(search).toHaveBeenCalledTimes(callsBeforeInput);
    expect(await screen.findByRole("option", { name: /000001.*平安银行/ })).toBeInTheDocument();
    expect(search).toHaveBeenCalledWith("平安");
  });

  it("selects the first valid candidate only when no selection exists", async () => {
    renderSelector();
    await waitFor(() => expect(new URL(window.location.href).searchParams.get("symbol")).toBe("600000"));
  });

  it("does not replace an explicit selection when candidates refresh", async () => {
    const view = renderSelector();
    await screen.findByRole("button", { pressed: true });
    fireEvent.click(screen.getByRole("tab", { name: "波段候选" }));
    fireEvent.click(screen.getByRole("button", { pressed: false }));
    expect(new URL(window.location.href).searchParams.get("symbol")).toBe("000001");
    view.rerender(<SelectedInstrumentProvider><StockSelector loadCandidates={() => Promise.resolve(empty)} search={() => Promise.resolve(searchResult)} /></SelectedInstrumentProvider>);
    await screen.findByText("本地候选池为空");
    expect(new URL(window.location.href).searchParams.get("symbol")).toBe("000001");
  });

  it("does not guess a stock when the candidate pool is empty", async () => {
    renderSelector({ loadCandidates: () => Promise.resolve(empty) });
    expect(await screen.findByText("本地候选池为空")).toBeInTheDocument();
    expect(new URL(window.location.href).searchParams.has("symbol")).toBe(false);
    expect(screen.getByText("尚未选择 A 股")).toBeInTheDocument();
  });

  it("stores watchlist symbols under the A-share-only key", async () => {
    renderSelector();
    await screen.findByRole("button", { pressed: true });
    fireEvent.click(screen.getByRole("button", { name: "将 600000 加入自选" }));
    await waitFor(() => expect(localStorage.getItem("qibao.a_share.watchlist.v1")).toBe('["600000"]'));
    expect(localStorage.getItem("qibao.watchlist")).toBeNull();
  });

  it("restores watchlist identity after the stock leaves all candidate lists", async () => {
    localStorage.setItem("qibao.a_share.watchlist.v1", '["000001"]');
    renderSelector({ loadCandidates: () => Promise.resolve(empty) });
    fireEvent.click(screen.getByRole("tab", { name: "自选股" }));
    expect(await screen.findByText("平安银行")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /000001.*平安银行/ })).toBeInTheDocument();
  });

  it("shows a search failure reason and retries the same query", async () => {
    let attempts = 0;
    const search = vi.fn((query: string) => {
      if (query !== "平安") return Promise.resolve(query === "600000" ? puFaResult : searchResult);
      attempts += 1;
      return attempts === 1 ? Promise.reject(new Error("目录暂不可用")) : Promise.resolve(searchResult);
    });
    renderSelector({ search });
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索 A 股" }), { target: { value: "平安" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("股票搜索暂不可用，请稍后重试。");
    expect(screen.queryByText("目录暂不可用")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试搜索" }));
    expect(await screen.findByRole("option", { name: /000001.*平安银行/ })).toBeInTheDocument();
    expect(search.mock.calls.filter(([query]) => query === "平安")).toHaveLength(2);
  });

  it("distinguishes an unavailable verification source from an unknown stock", async () => {
    renderSelector({
      loadCandidates: () => Promise.resolve(empty),
      search: (query) => Promise.resolve({
        query,
        items: [],
        source_status: "unavailable",
        server_time: "2026-07-16T09:30:00+08:00",
      }),
    });

    fireEvent.change(screen.getByRole("searchbox", { name: "搜索 A 股" }), {
      target: { value: "600519" },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("行情验证源暂不可用");
    expect(screen.queryByText("没有找到已验证的 A 股")).not.toBeInTheDocument();
  });

  it("adds a search result to watchlist", async () => {
    renderSelector();
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索 A 股" }), { target: { value: "平安" } });
    await screen.findByRole("option", { name: /000001.*平安银行/ });
    fireEvent.click(screen.getByRole("button", { name: "将 000001 加入自选" }));
    expect(localStorage.getItem("qibao.a_share.watchlist.v1")).toBe('["000001"]');
  });

  it("shows verified historical price without presenting it as live quote data", async () => {
    renderSelector();
    await screen.findByRole("button", { pressed: true });
    expect(await screen.findByText(/浦发银行/)).toBeInTheDocument();
    expect(screen.getByText("最近收盘 10.25 元")).toBeInTheDocument();
    expect(screen.getByText("近 20 日 +4.00%")).toBeInTheDocument();
    expect(screen.getByText(/近 5 日 \+1\.49%/)).toBeInTheDocument();
    expect(screen.getByText("数据日 2026-07-14")).toBeInTheDocument();
    expect(screen.queryByText("最新价不可用")).not.toBeInTheDocument();
    expect(screen.queryByText("当前涨跌不可用")).not.toBeInTheDocument();
  });

  it("polls candidates without replacing an explicit search selection", async () => {
    vi.useFakeTimers();
    const loadCandidates = vi.fn(() => Promise.resolve(first));
    renderSelector({ loadCandidates, pollIntervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(1);
    fireEvent.click(screen.getByRole("tab", { name: "波段候选" }));
    fireEvent.click(screen.getByRole("button", { pressed: false }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(loadCandidates).toHaveBeenCalledTimes(2);
    expect(new URL(window.location.href).searchParams.get("symbol")).toBe("000001");
    vi.useRealTimers();
  });

  it("links tabs to their panel and supports arrow-key switching", async () => {
    renderSelector();
    const short = screen.getByRole("tab", { name: "短线候选" });
    expect(short).toHaveAttribute("aria-controls", "stock-selector-panel");
    fireEvent.keyDown(short, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "波段候选" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "stock-selector-tab-swing");
  });

  it("invalidates an in-flight search immediately when a new debounced query is typed", async () => {
    let resolveOld!: (value: InstrumentSearchResponse) => void;
    const old = new Promise<InstrumentSearchResponse>((resolve) => { resolveOld = resolve; });
    const search = vi.fn((query: string) => query === "旧词" ? old : Promise.resolve(searchResult));
    renderSelector({ loadCandidates: () => Promise.resolve(empty), search });
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索 A 股" }), { target: { value: "旧词" } });
    await waitFor(() => expect(search).toHaveBeenCalledWith("旧词"));
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索 A 股" }), { target: { value: "新词" } });
    resolveOld({ ...searchResult, query: "旧词", items: [{ ...searchResult.items[0], name: "旧结果" }] });
    await Promise.resolve();
    expect(screen.queryByText("旧结果")).not.toBeInTheDocument();
    expect(await screen.findByText("平安银行")).toBeInTheDocument();
  });

  it("keeps a watchlist identity error visible and retries that symbol", async () => {
    localStorage.setItem("qibao.a_share.watchlist.v1", '["000001"]');
    let attempts = 0;
    const search = vi.fn((query: string) => {
      if (query !== "000001") return Promise.resolve(puFaResult);
      attempts += 1;
      return attempts === 1 ? Promise.reject(new Error("身份目录离线")) : Promise.resolve(searchResult);
    });
    renderSelector({ loadCandidates: () => Promise.resolve(empty), search });
    fireEvent.click(screen.getByRole("tab", { name: "自选股" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("股票身份数据暂不可用，请稍后重试。");
    expect(screen.queryByText("身份目录离线")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试 000001 身份" }));
    expect(await screen.findByText("平安银行")).toBeInTheDocument();
  });

  it("removes convertible bonds and invalid codes from persisted A-share watchlist", () => {
    localStorage.setItem("qibao.a_share.watchlist.v1", '["600000","113065","123001","not-code"]');
    renderSelector({ loadCandidates: () => Promise.resolve(empty) });
    expect(localStorage.getItem("qibao.a_share.watchlist.v1")).toBe('["600000"]');
  });

  it("ignores an older candidate refresh that resolves after a newer refresh", async () => {
    let resolveOld!: (value: CandidateBoard) => void;
    const old = new Promise<CandidateBoard>((resolve) => { resolveOld = resolve; });
    const loadCandidates = vi.fn().mockReturnValueOnce(old).mockResolvedValue(empty);
    renderSelector({ loadCandidates });
    fireEvent.click(screen.getByRole("button", { name: "刷新候选" }));
    expect(await screen.findByText("本地候选池为空")).toBeInTheDocument();
    resolveOld(first);
    await Promise.resolve();
    expect(screen.queryByRole("button", { pressed: true })).not.toBeInTheDocument();
  });

  it("only handles horizontal arrow keys and prevents their default behavior", () => {
    renderSelector();
    const short = screen.getByRole("tab", { name: "短线候选" });
    const vertical = new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true });
    act(() => { short.dispatchEvent(vertical); });
    expect(vertical.defaultPrevented).toBe(false);
    expect(short).toHaveAttribute("aria-selected", "true");
    const horizontal = new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true });
    act(() => { short.dispatchEvent(horizontal); });
    expect(horizontal.defaultPrevented).toBe(true);
    expect(screen.getByRole("tab", { name: "波段候选" })).toHaveAttribute("aria-selected", "true");
  });

  it("does not let an old identity failure overwrite a newer successful retry", async () => {
    localStorage.setItem("qibao.a_share.watchlist.v1", '["000001"]');
    let rejectOld!: (reason: Error) => void;
    const old = new Promise<InstrumentSearchResponse>((_, reject) => { rejectOld = reject; });
    const search = vi.fn().mockReturnValueOnce(old).mockResolvedValue(searchResult);
    renderSelector({ loadCandidates: () => Promise.resolve(empty), search });
    fireEvent.click(screen.getByRole("tab", { name: "自选股" }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "刷新候选" }));
    expect(await screen.findByText("平安银行")).toBeInTheDocument();
    await act(async () => { rejectOld(new Error("迟到的旧错误")); await old.catch(() => undefined); });
    await waitFor(() => expect(screen.queryByText("迟到的旧错误")).not.toBeInTheDocument());
    expect(screen.getByText("平安银行")).toBeInTheDocument();
  });

  it("does not let an old identity success replace a newer successful retry", async () => {
    localStorage.setItem("qibao.a_share.watchlist.v1", '["000001"]');
    let resolveOld!: (value: InstrumentSearchResponse) => void;
    const old = new Promise<InstrumentSearchResponse>((resolve) => { resolveOld = resolve; });
    const newer = { ...searchResult, items: [{ ...searchResult.items[0], name: "新名称" }] };
    const search = vi.fn().mockReturnValueOnce(old).mockResolvedValue(newer);
    renderSelector({ loadCandidates: () => Promise.resolve(empty), search });
    fireEvent.click(screen.getByRole("tab", { name: "自选股" }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "刷新候选" }));
    expect(await screen.findByText("新名称")).toBeInTheDocument();
    await act(async () => { resolveOld(searchResult); await old; });
    await waitFor(() => expect(screen.queryByText("平安银行")).not.toBeInTheDocument());
    expect(screen.getByText("新名称")).toBeInTheDocument();
  });
});
