import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NewsIntelligenceView } from "./NewsIntelligenceView";
import type { NewsIntelligenceBundle } from "./types";


const bundle: NewsIntelligenceBundle = {
  events: [{
    event_id: "event-1", event_type: "industrial_policy", headline: "先进制造专项政策发布",
    occurred_at: "2026-07-14T01:00:00Z", normalized_at: "2026-07-14T01:01:00Z",
    affected_instruments: [["a_share", "600000"]], industries: ["高端制造"],
    themes: ["政策支持"], association_confidence: "1", review_state: "verified",
    citations: [
      { citation_id: "citation-1", article_id: "article-1", canonical_url: "https://news.example/1", publisher: "测试来源", published_at: "2026-07-14T01:00:00Z", quoted_text: "政策支持先进制造", content_hash: "a".repeat(64) },
      { citation_id: "citation-2", article_id: "article-2", canonical_url: "https://news.example/2", publisher: "相反来源", published_at: "2026-07-14T01:00:00Z", quoted_text: "政策执行仍有不确定性", content_hash: "b".repeat(64) },
    ],
  }],
  interpretations: [{
    interpretation_id: "interpretation-1", event_id: "event-1", generated_at: "2026-07-14T01:02:00Z",
    provider: "cloud", model: "model-1", prompt_version: "news-v1", latency_ms: 125,
    degraded: false, impact_direction: "uncertain", confidence: "0.42",
    contrary_citation_ids: ["citation-2"], provider_attempts: 1,
    invalid_output_count: 0, provider_error_count: 0,
    statements: [
      { statement_id: "s1", kind: "fact", text: "专项政策已经发布。", citation_ids: ["citation-1"] },
      { statement_id: "s2", kind: "interpretation", text: "可能改善预期，但不是买入信号。", citation_ids: [] },
    ], citations: [],
  }],
  quality: { article_count: 2, cluster_count: 1, event_count: 1, interpretation_count: 1, correction_count: 0, citation_coverage: "1.0000", duplicate_rate: "0.5000", invalid_json_rate: "0.0000", provider_error_rate: "0.0000", human_correction_rate: "0.0000" },
  corrections: [], briefings: [],
};


describe("NewsIntelligenceView", () => {
  it("defaults to the selected A-share and excludes events bound to another stock", async () => {
    const filteredBundle: NewsIntelligenceBundle = {
      ...bundle,
      events: [
        ...bundle.events,
        { ...bundle.events[0], event_id: "event-other", headline: "其他股票事件", affected_instruments: [["a_share", "000001"]] },
        { ...bundle.events[0], event_id: "event-market", headline: "全市场事件", affected_instruments: [] },
      ],
    };
    render(<NewsIntelligenceView selectedSymbol="600000" loadBundle={() => Promise.resolve(filteredBundle)} syncNews={() => Promise.resolve({ fetched: 0 })} createCorrection={() => Promise.resolve()} />);

    expect(await screen.findByText("当前标的 600000")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "先进制造专项政策发布" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "全市场事件" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "其他股票事件" })).not.toBeInTheDocument();
  });

  it("reloads on same-route symbol history changes without accepting the stale response", async () => {
    let resolveOld!: (value: NewsIntelligenceBundle) => void;
    const oldRequest = new Promise<NewsIntelligenceBundle>((resolve) => { resolveOld = resolve; });
    const loadBundle = vi.fn().mockReturnValueOnce(oldRequest).mockResolvedValueOnce({ ...bundle, events: [{ ...bundle.events[0], affected_instruments: [["a_share", "000001"]], headline: "新标的事件" }] });
    const view = render(<NewsIntelligenceView selectedSymbol="600000" loadBundle={loadBundle} syncNews={() => Promise.resolve({})} createCorrection={() => Promise.resolve()} />);
    view.rerender(<NewsIntelligenceView selectedSymbol="000001" loadBundle={loadBundle} syncNews={() => Promise.resolve({})} createCorrection={() => Promise.resolve()} />);
    expect(await screen.findByRole("heading", { name: "新标的事件" })).toBeInTheDocument();
    resolveOld(bundle);
    await Promise.resolve();
    expect(screen.getByRole("heading", { name: "新标的事件" })).toBeInTheDocument();
  });

  it("invalidates deferred collect and correction work when the symbol changes", async () => {
    let resolveSync!: () => void;
    let resolveCorrection!: () => void;
    const syncNews = vi.fn(() => new Promise<Record<string, number>>((resolve) => { resolveSync = () => resolve({ fetched: 1 }); }));
    const createCorrection = vi.fn(() => new Promise<void>((resolve) => { resolveCorrection = resolve; }));
    const loadBundle = vi.fn().mockResolvedValue(bundle);
    const view = render(<NewsIntelligenceView selectedSymbol="600000" loadBundle={loadBundle} syncNews={syncNews} createCorrection={createCorrection} />);
    await screen.findByRole("heading", { name: "先进制造专项政策发布" });
    fireEvent.click(screen.getByRole("button", { name: "同步新闻" }));
    view.rerender(<NewsIntelligenceView selectedSymbol="000001" loadBundle={loadBundle} syncNews={syncNews} createCorrection={createCorrection} />);
    resolveSync();
    await Promise.resolve();
    expect(screen.queryByRole("heading", { name: "先进制造专项政策发布" })).not.toBeInTheDocument();

    view.rerender(<NewsIntelligenceView selectedSymbol="600000" loadBundle={loadBundle} syncNews={syncNews} createCorrection={createCorrection} />);
    await screen.findByRole("heading", { name: "先进制造专项政策发布" });
    fireEvent.click(screen.getByRole("button", { name: "查看 2 条证据" }));
    fireEvent.change(screen.getByLabelText("复核理由"), { target: { value: "待复核" } });
    fireEvent.click(screen.getByRole("button", { name: "确认并存档" }));
    view.rerender(<NewsIntelligenceView selectedSymbol="000001" loadBundle={loadBundle} syncNews={syncNews} createCorrection={createCorrection} />);
    expect(screen.queryByRole("dialog", { name: "事件证据" })).not.toBeInTheDocument();
    resolveCorrection();
    await Promise.resolve();
    expect(screen.queryByRole("heading", { name: "先进制造专项政策发布" })).not.toBeInTheDocument();
  });

  it("separates facts, interpretation, uncertainty, and contrary evidence", async () => {
    render(<NewsIntelligenceView loadBundle={() => Promise.resolve(bundle)} syncNews={() => Promise.resolve({ fetched: 0 })} createCorrection={() => Promise.resolve()} />);

    expect(await screen.findByRole("heading", { name: "先进制造专项政策发布" })).toBeInTheDocument();
    expect(screen.getByText("已核验事实")).toBeInTheDocument();
    expect(screen.getByText("模型解释")).toBeInTheDocument();
    expect(screen.getByText("不确定性较高")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看 2 条证据" }));
    expect(screen.getByRole("dialog", { name: "事件证据" })).toBeInTheDocument();
    expect(screen.getByText("相反证据")).toBeInTheDocument();
    expect(screen.getAllByText("政策执行仍有不确定性")).toHaveLength(2);
    expect(screen.queryByText("aaaaaaaaaaaaaaaa")).not.toBeInTheDocument();
  });

  it("shows beginner data status without backend or model telemetry", async () => {
    const createCorrection = vi.fn(() => Promise.resolve());
    render(<NewsIntelligenceView loadBundle={() => Promise.resolve(bundle)} syncNews={() => Promise.resolve({ fetched: 0 })} createCorrection={createCorrection} />);
    await screen.findByRole("heading", { name: "先进制造专项政策发布" });
    fireEvent.click(screen.getByRole("tab", { name: "数据状态" }));
    expect(screen.getByText("已核验新闻数")).toBeInTheDocument();
    expect(screen.getByText("关联当前股票数")).toBeInTheDocument();
    expect(screen.queryByText(/无效 JSON|模型结构|provider|prompt|人工修正率|重复率/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "事件时间线" }));
    fireEvent.click(screen.getByRole("button", { name: "查看 2 条证据" }));
    fireEvent.change(screen.getByLabelText("复核理由"), { target: { value: "确认政策主题归属" } });
    fireEvent.click(screen.getByRole("button", { name: "确认并存档" }));
    expect(createCorrection).toHaveBeenCalledWith(expect.objectContaining({ event_id: "event-1", review_state: "verified" }));
  });

  it("shows briefing content without rendering the input snapshot hash", async () => {
    const snapshotHash = "briefing-secret-hash-1234567890";
    const briefingBundle: NewsIntelligenceBundle = {
      ...bundle,
      briefings: [{
        report_id: "report-1", trading_date: "2026-07-14", phase: "premarket", generated_at: "2026-07-14T01:05:00Z",
        event_ids: ["event-1"], interpretation_ids: ["interpretation-1"], input_snapshot_hash: snapshotHash,
        sections: { policy_event_ids: ["event-1"], risk_event_ids: [], watchlist: [["a_share", "600000"]], signal_outcome_ids: [], error_codes: [], next_day_observations: [] },
      }],
    };
    const view = render(<NewsIntelligenceView loadBundle={() => Promise.resolve(briefingBundle)} syncNews={() => Promise.resolve({})} createCorrection={() => Promise.resolve()} />);
    await screen.findByRole("heading", { name: "先进制造专项政策发布" });
    fireEvent.click(screen.getByRole("tab", { name: "每日简报" }));
    expect(screen.getByText("盘前")).toBeInTheDocument();
    expect(screen.getByText("2026-07-14")).toBeInTheDocument();
    expect(screen.getByText("1 个事件 · 1 条解释")).toBeInTheDocument();
    expect(screen.queryByText(snapshotHash)).not.toBeInTheDocument();
    expect(view.container.querySelector(".briefing-ledger code")).toBeNull();
  });

  it("sanitizes hostile news errors", async () => {
    render(<NewsIntelligenceView loadBundle={() => Promise.reject(new Error("中书省 provider secret https://internal"))} syncNews={() => Promise.resolve({})} createCorrection={() => Promise.resolve()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("新闻数据暂不可用，请稍后重试。");
    expect(screen.queryByText(/中书省|provider|https/)).not.toBeInTheDocument();
  });
});
