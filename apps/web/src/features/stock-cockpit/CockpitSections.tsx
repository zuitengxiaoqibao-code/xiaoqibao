import { ChevronDown, Database } from "lucide-react";

import type { CockpitSection } from "./types";

const definitions = [
  ["market", "实时行情"], ["price_volume", "量价"], ["trend", "趋势"], ["valuation", "估值"],
  ["fundamentals", "基本面"], ["funds", "资金流"], ["news", "新闻与事件"],
  ["industry", "行业与题材"], ["risk", "风险"],
] as const;

const statusNames: Record<CockpitSection["status"], string> = {
  ready: "可用", partial: "部分可用", stale: "已陈旧", unavailable: "不可用", blocked: "已拦截",
};
const reasonNames: Record<string, string> = {
  source_authorization_required: "数据源尚未授权",
  diagnosis_unavailable: "诊断数据暂不可用",
  diagnosis_section_unavailable: "该分区数据暂不可用",
  observed_after_cutoff: "数据晚于当前快照截止时间",
};
const sourceNames: Record<string, string> = {
  tencent: "腾讯行情", mootdx: "通达信数据", eastmoney: "东方财富公开数据", baidu: "百度行情",
  "mootdx-finance": "通达信财务快照",
  "eastmoney-fund-flow": "东方财富资金流",
  "eastmoney-stock-classification": "东方财富行业与板块",
  "frozen-news-events": "已核验新闻事件",
  cockpit: "本地研判数据", assessment: "本地研判数据",
};
const metricNames: Record<string, string> = {
  latest_price: "最新价", price: "最新价", change_percent: "涨跌幅", turnover_rate: "换手率",
  open: "开盘价", high: "最高价", low: "最低价", close: "收盘价",
  volume: "成交量", amount: "成交额", average_amount_20d: "20日平均成交额", volume_ratio: "量比",
  return_5d: "近5日涨跌", return_20d: "近20日涨跌", distance_ma20: "距20日均线",
  volatility_20d: "20日波动率", drawdown_60d: "60日最大回撤",
  pe_ttm: "市盈率（TTM）", pb: "市净率", market_cap_yi: "总市值",
  report_period: "报告期", data_updated_on: "数据更新日", industry: "所属行业",
  eps: "每股收益", roe: "净资产收益率", net_profit: "净利润", revenue: "营业收入",
  book_value_per_share: "每股净资产", total_shares: "总股本",
  latest_trade_date: "最新交易日", latest_main_net: "当日主力净额",
  latest_super_net: "当日超大单净额", latest_large_net: "当日大单净额",
  main_net_5d: "近5日主力净额", main_net_20d: "近20日主力净额",
  intraday_main_net: "盘中主力净额", daily_sample_count: "日线样本",
  intraday_sample_count: "盘中样本", flow_direction: "资金方向",
  event_count: "关联事件", adverse_event_count: "重大反方事件",
  board_tags: "板块标签", event_industries: "新闻事件行业标签",
  missing_section_count: "缺失分区", symbol: "股票代码",
};

const percentMetrics = new Set(["change_percent", "turnover_rate", "roe"]);
const fractionPercentMetrics = new Set(["return_5d", "return_20d", "distance_ma20", "volatility_20d", "drawdown_60d"]);
const priceMetrics = new Set(["latest_price", "price", "open", "high", "low", "close", "eps", "book_value_per_share"]);
const moneyMetrics = new Set(["average_amount_20d", "net_profit", "revenue"]);
const fundFlowMoneyMetrics = new Set([
  "latest_main_net", "latest_super_net", "latest_large_net",
  "main_net_5d", "main_net_20d", "intraday_main_net",
]);
const flowDirectionNames: Record<string, string> = {
  inflow: "净流入", outflow: "净流出", balanced: "基本平衡",
};

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "未提供";
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未提供";
  if (Array.isArray(value)) return value.length && value.every((item) => ["string", "number", "boolean"].includes(typeof item)) ? value.map(String).join("、") : "未提供可展示说明";
  if (!["string", "number", "boolean"].includes(typeof value)) return "未提供可展示说明";
  return String(value);
}

function formatMetric(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "未提供";
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    if (fundFlowMoneyMetrics.has(key)) {
      const amount = numeric / 100_000_000;
      return `${amount > 0 ? "+" : ""}${amount.toFixed(2)} 亿元`;
    }
    if (percentMetrics.has(key)) return `${numeric.toFixed(2)}%`;
    if (fractionPercentMetrics.has(key)) return `${(numeric * 100).toFixed(2)}%`;
    if (priceMetrics.has(key)) return `${numeric.toFixed(2)} 元`;
    if (moneyMetrics.has(key)) return `${(numeric / 100_000_000).toFixed(2)} 亿元`;
    if (key === "market_cap_yi") return `${numeric.toFixed(2)} 亿元`;
    if (key === "total_shares") return `${(numeric / 100_000_000).toFixed(2)} 亿股`;
    if (key === "pe_ttm" || key === "pb") return `${numeric.toFixed(2)} 倍`;
    if (key === "event_count" || key === "adverse_event_count" || key === "missing_section_count") return `${numeric} 项`;
    if (key === "daily_sample_count") return `${numeric} 个交易日`;
    if (key === "intraday_sample_count") return `${numeric} 个分钟点`;
    if (key === "volume_ratio") return numeric.toFixed(2);
  }
  if (key === "flow_direction") return flowDirectionNames[String(value)] ?? "未提供";
  return renderValue(value);
}

function SectionBand({ sectionKey, title, section }: { sectionKey: string; title: string; section: CockpitSection }) {
  const rawMetrics = section.payload.metrics && typeof section.payload.metrics === "object" ? section.payload.metrics as Record<string, unknown> : {};
  const metrics = Object.keys(metricNames).filter((key) => key in rawMetrics).map((key) => [key, rawMetrics[key]] as const);
  const evidenceIds = Array.isArray(section.payload.evidence_ids)
    ? section.payload.evidence_ids.filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    : [];
  const unavailableFundsReason = sectionKey === "funds"
    && section.reason === "diagnosis_section_unavailable"
    ? "东方财富资金流暂未返回可核验数据，本项未参与当前研判。"
    : null;
  const reason = unavailableFundsReason
    ?? (section.reason ? reasonNames[section.reason] ?? "未提供可展示说明" : null);
  const source = sourceNames[section.source] ?? "公开数据来源";
  return <section className={`cockpit-section status-${section.status}`} aria-labelledby={`cockpit-${sectionKey}`}>
    <header><div><Database size={15} /><h3 id={`cockpit-${sectionKey}`}>{title}</h3></div><span>{statusNames[section.status]}</span></header>
    {reason && <p className="section-reason">{reason}</p>}
    {section.status === "unavailable" || section.status === "blocked" ? !reason && <p className="section-degraded">当前没有可验证数据</p> : <>
      {metrics.length > 0 ? <details><summary><ChevronDown size={14} />查看详细指标</summary><dl>{metrics.map(([key, value]) => <div key={key}><dt>{metricNames[key] ?? key}</dt><dd>{formatMetric(key, value)}</dd></div>)}</dl></details> : <p className="section-summary">当前快照没有可展开的指标。</p>}
      {evidenceIds.length > 0 && <details className="section-evidence"><summary><ChevronDown size={14} />{evidenceIds.length} 条证据编号</summary><ul>{evidenceIds.map((id) => <li key={id}><code>{id}</code></li>)}</ul></details>}
    </>}
    <footer><span>来源：{source}</span><span>时间：{formatTime(section.observed_at)}</span>{section.status === "stale" && <span>当前数据已陈旧</span>}</footer>
  </section>;
}

export function CockpitSections({ sections }: { sections: Record<string, CockpitSection> }) {
  const visible = definitions.filter(([key]) => sections[key]);
  return <details className="cockpit-data"><summary><span><Database size={17} /><b>数据详情</b></span><small>{visible.filter(([key]) => sections[key].status === "ready").length}/{visible.length} 类数据可用</small><ChevronDown size={16} /></summary>
    <div className="cockpit-section-list">{visible.map(([key, title]) => <SectionBand key={key} sectionKey={key} title={title} section={sections[key]} />)}</div>
  </details>;
}
