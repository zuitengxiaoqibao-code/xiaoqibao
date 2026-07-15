import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SelectedInstrumentProvider } from "../instrument-selection/SelectedInstrumentProvider";
import type { CandidateBoard } from "../a-shares/types";
import { StockSelector } from "./StockSelector";
import type { InstrumentSearchResponse } from "./types";

const factor = {
  symbol: "600000", as_of: "2026-07-15", close: "10.25", return_5d: "0.0149",
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
  items: [{ asset: "a_share", symbol: "000001", name: "平安银行", exchange: "sz", observed_at: "2026-07-15T09:29:00+08:00", quote_quality: "ready" }],
};

function renderSelector(props: Partial<React.ComponentProps<typeof StockSelector>> = {}) {
  return render(<SelectedInstrumentProvider><StockSelector
    loadCandidates={() => Promise.resolve(first)} search={() => Promise.resolve(searchResult)} {...props}
  /></SelectedInstrumentProvider>);
}

describe("StockSelector", () => {
  beforeEach(() => { window.history.replaceState({}, "", "/"); localStorage.clear(); vi.useRealTimers(); });

  it("offers candidates and searches by code or name after 250ms", async () => {
    const search = vi.fn(() => Promise.resolve(searchResult));
    renderSelector({ search });
    expect(await screen.findByRole("button", { name: /600000/ })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索 A 股" }), { target: { value: "平安" } });
    expect(search).not.toHaveBeenCalled();
    expect(await screen.findByRole("option", { name: /000001.*平安银行/ })).toBeInTheDocument();
    expect(search).toHaveBeenCalledWith("平安");
  });

  it("selects the first valid candidate only when no selection exists", async () => {
    renderSelector();
    await waitFor(() => expect(new URL(window.location.href).searchParams.get("symbol")).toBe("600000"));
  });

  it("does not replace an explicit selection when candidates refresh", async () => {
    const view = renderSelector();
    await screen.findByRole("button", { name: /600000/ });
    fireEvent.click(screen.getByRole("tab", { name: "波段候选" }));
    fireEvent.click(screen.getByRole("button", { name: /000001/ }));
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
    await screen.findByRole("button", { name: /600000/ });
    fireEvent.click(screen.getByRole("button", { name: "加入自选" }));
    await waitFor(() => expect(localStorage.getItem("qibao.a_share.watchlist.v1")).toBe('["600000"]'));
    expect(localStorage.getItem("qibao.watchlist")).toBeNull();
  });
});
