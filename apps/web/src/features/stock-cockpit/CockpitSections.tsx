import { ChevronDown, Database } from "lucide-react";

import type { CockpitSection } from "./types";

const definitions = [
  ["market", "实时行情"], ["price_volume", "量价"], ["trend", "趋势"], ["valuation", "估值"],
  ["fundamentals", "基本面"], ["news", "新闻与事件"],
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
  cockpit: "本地研判数据", assessment: "本地研判数据",
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
  if (Array.isArray(value)) return value.length && value.every((item) => ["string", "number", "boolean"].includes(typeof item)) ? value.map(String).join("、") : "未提供可展示说明";
  if (!["string", "number", "boolean"].includes(typeof value)) return "未提供可展示说明";
  return String(value).slice(0, 120);
}

function SectionBand({ sectionKey, title, section }: { sectionKey: string; title: string; section: CockpitSection }) {
  const rawMetrics = section.payload.metrics && typeof section.payload.metrics === "object" ? section.payload.metrics as Record<string, unknown> : {};
  const metrics = Object.keys(metricNames).filter((key) => key in rawMetrics).map((key) => [key, rawMetrics[key]] as const);
  const reason = section.reason ? reasonNames[section.reason] ?? "未提供可展示说明" : null;
  const source = sourceNames[section.source] ?? "公开数据来源";
  return <section className={`cockpit-section status-${section.status}`} aria-labelledby={`cockpit-${sectionKey}`}>
    <header><div><Database size={15} /><h3 id={`cockpit-${sectionKey}`}>{title}</h3></div><span>{statusNames[section.status]}</span></header>
    {reason && <p className="section-reason">{reason}</p>}
    {section.status === "unavailable" || section.status === "blocked" ? !reason && <p className="section-degraded">当前没有可验证数据</p> : <>
      {metrics.length > 0 ? <details><summary><ChevronDown size={14} />查看详细指标</summary><dl>{metrics.map(([key, value]) => <div key={key}><dt>{metricNames[key] ?? key}</dt><dd>{renderValue(value)}</dd></div>)}</dl></details> : <p className="section-summary">当前快照没有可展开的指标。</p>}
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
