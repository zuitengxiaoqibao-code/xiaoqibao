import { ExternalLink, Newspaper, ShieldAlert } from "lucide-react";

import type { PhaseContext, PhaseNewsEvent } from "./types";

const marketStateNames: Record<NonNullable<PhaseContext["market_state"]>, string> = {
  strong: "偏强",
  range: "震荡",
  weak: "偏弱",
  insufficient_data: "数据不足",
};

const qualityReasonNames: Record<string, string> = {
  candidate_history_unavailable: "候选股历史行情不足",
  candidate_as_of_after_trading_date: "候选池日期晚于本交易日",
  candidate_snapshot_after_window: "候选池数据晚于本阶段截止时间",
  compliance_unavailable: "合规检查数据不可用",
  compliance_snapshot_after_window: "合规检查晚于本阶段截止时间",
  compliance_not_allowed: "当前数据来源未通过合规授权",
  risk_unavailable: "市场风险数据不可用",
  risk_snapshot_after_window: "市场风险数据晚于本阶段截止时间",
  candidate_universe_empty: "当前没有达到规则门槛的候选股票",
  ai_unavailable: "AI 补充解释不可用，确定性结果仍保留",
  block_reason_unrecorded: "该历史快照未记录具体拦截原因",
};

function eventTags(event: PhaseNewsEvent): string {
  return [...event.industries, ...event.themes].join(" · ") || "行业与主题未标注";
}

function confidence(value: string | null): string | null {
  if (value === null) return null;
  const percent = Number(value) * 100;
  return Number.isFinite(percent) ? `${Math.round(percent)}% 关联可信度` : null;
}

function newsStatus(context: PhaseContext) {
  if (context.news.status === "unavailable") {
    return <div className="phase-context-warning" role="status">
      <ShieldAlert size={16} />
      <div><b>新闻证据读取失败</b><p>阶段结论仍保留，不会用推测内容补位。</p></div>
    </div>;
  }
  if (context.news.status === "partial") {
    return <div className="phase-context-warning" role="status">
      <ShieldAlert size={16} />
      <div><b>{context.news.missing_event_ids.length} 条快照新闻引用当前无法读取</b><p>不会用推测内容补位。</p></div>
    </div>;
  }
  if (context.news.status === "empty") {
    return <p className="phase-context-empty">本阶段快照未引用已验证新闻事件。</p>;
  }
  return null;
}

export function PhaseContextPanel({ context }: { context?: PhaseContext }) {
  if (!context) return null;
  const marketState = context.market_state ? marketStateNames[context.market_state] : "状态未记录";
  return <section className="phase-context" aria-label="阶段依据">
    <header>
      <div>
        <span>市场与事件依据</span>
        <h2>市场{marketState}</h2>
      </div>
      <div className="phase-context-metrics">
        <span>{context.candidate_snapshot_id ? "候选池已冻结" : "候选池未引用"}</span>
        <span>{context.risk_event_count} 项风险证据</span>
        <span>{context.news.events.length} 条已验证新闻</span>
      </div>
    </header>
    {context.quality_reasons.length > 0 && <section className="phase-quality-reasons">
      <h3>为什么当前没有完整建议</h3>
      <ul>{context.quality_reasons.map((reason) => <li key={reason}>{qualityReasonNames[reason] ?? `已记录的数据质量问题：${reason}`}</li>)}</ul>
    </section>}
    {context.news.events.length > 0 && <div className="phase-event-list">
      {context.news.events.map((event) => <article key={event.event_id}>
        <div className="phase-event-heading">
          <Newspaper size={16} />
          <div><span>{eventTags(event)}</span><h3>{event.headline}</h3></div>
        </div>
        <div className="phase-event-meta">
          <span>{event.affected_symbols.length ? `关联 ${event.affected_symbols.join("、")}` : "市场级事件"}</span>
          {confidence(event.association_confidence) && <span>{confidence(event.association_confidence)}</span>}
          <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString("zh-CN")}</time>
          {event.source_url && event.publisher && <a href={event.source_url} target="_blank" rel="noreferrer" aria-label={event.publisher}>{event.publisher}<ExternalLink size={13} /></a>}
        </div>
      </article>)}
    </div>}
    {newsStatus(context)}
    {context.window_end && <footer>证据窗口截至 {new Date(context.window_end).toLocaleString("zh-CN")}</footer>}
  </section>;
}
