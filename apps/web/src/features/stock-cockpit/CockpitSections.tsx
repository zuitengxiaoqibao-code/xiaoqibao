import { ChevronDown, Database, ShieldAlert } from "lucide-react";

import type { CockpitSection } from "./types";

const definitions = [
  ["market", "实时行情"], ["price_volume", "量价"], ["trend", "趋势"], ["valuation", "估值"],
  ["fundamentals", "基本面"], ["funds", "资金"], ["news", "新闻与事件"],
  ["industry", "行业与题材"], ["risk", "风险"], ["backtest", "回测"],
] as const;

const statusNames: Record<CockpitSection["status"], string> = {
  ready: "可用", partial: "部分可用", stale: "已陈旧", unavailable: "不可用", blocked: "已拦截",
};
const reasonNames: Record<string, string> = {
  fund_data_not_connected: "资金数据尚未接入",
  backtest_not_run: "尚未为该股票运行回测",
  source_authorization_required: "数据源尚未授权",
  diagnosis_unavailable: "诊断数据暂不可用",
  diagnosis_section_unavailable: "该分区数据暂不可用",
  observed_after_cutoff: "数据晚于当前快照截止时间",
};
const metricNames: Record<string, string> = {
  latest_price: "最新价", change_percent: "涨跌幅", open: "开盘价", high: "最高价", low: "最低价",
  volume: "成交量", amount: "成交额", pe_ttm: "市盈率（TTM）", pb: "市净率", eps: "每股收益",
  industry: "所属行业", symbol: "股票代码",
};

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "未提供";
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未提供";
  if (Array.isArray(value)) return value.length ? value.map(renderValue).join("、") : "暂无记录";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function SectionBand({ sectionKey, title, section }: { sectionKey: string; title: string; section?: CockpitSection }) {
  if (!section) section = { status: "unavailable", source: "cockpit", observed_at: null, snapshot_id: null, reason: "diagnosis_section_unavailable", payload: {} };
  const metrics = section.payload.metrics && typeof section.payload.metrics === "object" ? Object.entries(section.payload.metrics as Record<string, unknown>) : [];
  const explanation = typeof section.payload.explanation === "string" ? section.payload.explanation : null;
  const reason = section.reason ? reasonNames[section.reason] ?? section.reason : null;
  return <section className={`cockpit-section status-${section.status}`} aria-labelledby={`cockpit-${sectionKey}`}>
    <header><div><Database size={15} /><h3 id={`cockpit-${sectionKey}`}>{title}</h3></div><span>{statusNames[section.status]}</span></header>
    {reason && <div className="section-reason"><ShieldAlert size={15} /><p>{reason}</p></div>}
    {section.status === "unavailable" || section.status === "blocked" ? !reason && <div className="section-degraded"><ShieldAlert size={16} /><p>当前没有可验证数据</p></div> : <>
      {explanation && <p className="section-summary">{explanation}</p>}
      {metrics.length > 0 ? <details><summary><ChevronDown size={14} />查看详细指标</summary><dl>{metrics.map(([key, value]) => <div key={key}><dt>{metricNames[key] ?? key}</dt><dd>{renderValue(value)}</dd></div>)}</dl></details> : <p className="section-summary">当前快照没有可展开的指标。</p>}
    </>}
    <footer><span>来源：{section.source}</span><span>观察时间：{formatTime(section.observed_at)}</span><span>快照：{section.snapshot_id ?? "未生成"}</span></footer>
  </section>;
}

export function CockpitSections({ sections }: { sections: Record<string, CockpitSection> }) {
  return <section className="cockpit-data" aria-labelledby="cockpit-data-title"><header className="cockpit-block-title"><div><p className="eyebrow">工部 / 冻结数据底稿</p><h2 id="cockpit-data-title">完整数据分区</h2></div><span>10 SECTIONS</span></header>
    <div className="cockpit-section-list">{definitions.map(([key, title]) => <SectionBand key={key} sectionKey={key} title={title} section={sections[key]} />)}</div>
  </section>;
}
