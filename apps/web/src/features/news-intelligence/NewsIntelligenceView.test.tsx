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
  });

  it("shows real quality ratios and submits a human correction", async () => {
    const createCorrection = vi.fn(() => Promise.resolve());
    render(<NewsIntelligenceView loadBundle={() => Promise.resolve(bundle)} syncNews={() => Promise.resolve({ fetched: 0 })} createCorrection={createCorrection} />);
    await screen.findByRole("heading", { name: "先进制造专项政策发布" });
    fireEvent.click(screen.getByRole("tab", { name: "质量监测" }));
    expect(screen.getByText("100.00%")).toBeInTheDocument();
    expect(screen.getByText("50.00%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "事件时间线" }));
    fireEvent.click(screen.getByRole("button", { name: "查看 2 条证据" }));
    fireEvent.change(screen.getByLabelText("复核理由"), { target: { value: "确认政策主题归属" } });
    fireEvent.click(screen.getByRole("button", { name: "确认并存档" }));
    expect(createCorrection).toHaveBeenCalledWith(expect.objectContaining({ event_id: "event-1", review_state: "verified" }));
  });
});
