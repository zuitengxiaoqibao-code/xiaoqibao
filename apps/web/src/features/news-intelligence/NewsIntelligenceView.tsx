import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, BookOpen, CheckCircle2, Clock3, FileSearch, RefreshCw, Scale, ShieldAlert, X } from "lucide-react";

import type { CorrectionInput, NewsEvent, NewsIntelligenceBundle } from "./types";

type Props = { selectedSymbol?: string | null; loadBundle: () => Promise<NewsIntelligenceBundle>; syncNews: () => Promise<Record<string, number>>; createCorrection: (input: CorrectionInput) => Promise<unknown>; openNewsCompliance?: () => void };
type Tab = "timeline" | "briefings" | "quality";
const phaseName = { premarket: "盘前", intraday: "盘中", postclose: "盘后" };
const directionName = { positive: "偏正面", negative: "偏负面", neutral: "中性", uncertain: "方向不确定" };
const percent = (value: string) => `${(Number(value) * 100).toFixed(2)}%`;

export function NewsIntelligenceView({ selectedSymbol, loadBundle, syncNews, createCorrection, openNewsCompliance }: Props) {
  const [bundle, setBundle] = useState<NewsIntelligenceBundle | null>(null);
  const [tab, setTab] = useState<Tab>("timeline");
  const [selected, setSelected] = useState<NewsEvent | null>(null);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const requestVersion = useRef(0);
  function filterSelectedBundle(loaded: NewsIntelligenceBundle, symbol: string | null | undefined) {
    if (!symbol) return loaded;
    return { ...loaded, events: loaded.events.filter((event) => event.affected_instruments.length === 0 || event.affected_instruments.some(([asset, code]) => asset === "a_share" && code === symbol)) };
  }
  async function runBundleRequest(work: () => Promise<NewsIntelligenceBundle>, failureMessage: string, mode: "loading" | "saving") {
    const request = ++requestVersion.current;
    const requestSymbol = selectedSymbol;
    if (mode === "loading") setLoading(true); else setSaving(true);
    setError("");
    try { const loaded = await work(); if (request === requestVersion.current) { setBundle(filterSelectedBundle(loaded, requestSymbol)); return true; } }
    catch (cause) { if (request === requestVersion.current) setError(cause instanceof Error ? cause.message : failureMessage); }
    finally { if (request === requestVersion.current) { setLoading(false); setSaving(false); } }
    return false;
  }
  useEffect(() => {
    requestVersion.current += 1;
    setSelected(null); setReason(""); setBundle(null); setSaving(false);
    void runBundleRequest(loadBundle, "情报流暂不可用", "loading");
    return () => { requestVersion.current += 1; };
  }, [loadBundle, selectedSymbol]);
  const interpretationByEvent = useMemo(() => new Map(bundle?.interpretations.map((item) => [item.event_id, item]) ?? []), [bundle]);
  async function collect() { await runBundleRequest(async () => { await syncNews(); return loadBundle(); }, "新闻同步失败", "loading"); }
  async function saveCorrection() {
    if (!selected || !reason.trim()) return;
    const correction = { event_id: selected.event_id, reason: reason.trim(), review_state: "verified" as const, affected_instruments: selected.affected_instruments, industries: selected.industries, themes: selected.themes };
    if (await runBundleRequest(async () => { await createCorrection(correction); return loadBundle(); }, "复核存档失败", "saving")) setReason("");
  }
  const selectedInterpretation = selected ? interpretationByEvent.get(selected.event_id) : undefined;
  const contrary = selected?.citations.filter((item) => selectedInterpretation?.contrary_citation_ids.includes(item.citation_id)) ?? [];
  return <main className="news-domain">
    <header className="news-header"><div><p className="eyebrow">新闻热点 / VERIFIED FEED</p><h1>每日情报流</h1><p>{selectedSymbol ? `当前标的 ${selectedSymbol}` : "全市场情报 · 尚未选择 A 股"}</p></div><button className="news-sync" onClick={() => void collect()} disabled={loading}><RefreshCw size={15}/>{loading ? "核验中" : "同步新闻"}</button></header>
    <div className="news-tabs" role="tablist"><button role="tab" aria-selected={tab === "timeline"} onClick={() => setTab("timeline")}>事件时间线</button><button role="tab" aria-selected={tab === "briefings"} onClick={() => setTab("briefings")}>每日简报</button><button role="tab" aria-selected={tab === "quality"} onClick={() => setTab("quality")}>质量监测</button></div>
    {error && <div className="news-error" role="alert"><AlertTriangle size={17}/><span>{error}</span>{error.includes("授权") && openNewsCompliance && <button onClick={openNewsCompliance}>检查数据授权</button>}</div>}
    {loading && !bundle && <div className="news-loading"><Clock3 size={18}/>正在读取冻结情报...</div>}
    {tab === "timeline" && bundle && <section className="intelligence-timeline">{bundle.events.length === 0 ? <div className="news-empty"><FileSearch size={28}/><b>暂无已归档事件</b></div> : [...bundle.events].sort((a,b) => b.occurred_at.localeCompare(a.occurred_at)).map((event) => { const interpretation = interpretationByEvent.get(event.event_id); const uncertain = !interpretation || interpretation.degraded || interpretation.impact_direction === "uncertain" || Number(interpretation.confidence) < .6; return <article className="intelligence-event" key={event.event_id}><div className="timeline-time"><time>{new Date(event.occurred_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time><span className={event.review_state}/></div><div className="event-body"><header><div><p>{event.event_type} · {event.review_state === "verified" ? "已复核" : "待复核"}</p><h2>{event.headline}</h2></div><div className={`impact ${interpretation?.impact_direction ?? "uncertain"}`}>{interpretation?.impact_direction === "positive" ? <ArrowUpRight/> : interpretation?.impact_direction === "negative" ? <ArrowDownRight/> : <Scale/>}<span>{directionName[interpretation?.impact_direction ?? "uncertain"]}<small>置信度 {percent(interpretation?.confidence ?? "0")}</small></span></div></header><div className="event-tags">{event.affected_instruments.map(([asset, code]) => <span key={`${asset}-${code}`}>{asset === "a_share" ? "A股" : "转债"} {code}</span>)}{event.industries.map((item) => <span key={item}>{item}</span>)}{event.themes.map((item) => <span key={item}>{item}</span>)}</div>{interpretation?.statements.map((statement) => <div className={`statement ${statement.kind}`} key={statement.statement_id}><b>{statement.kind === "fact" ? "已核验事实" : "模型解释"}</b><p>{statement.text}</p></div>)}{uncertain && <div className="uncertainty"><ShieldAlert size={15}/><span>不确定性较高</span><small>{interpretation?.degraded ? "模型已降级，仅保留确定性事实" : "关联或影响方向仍需人工复核"}</small></div>}<footer><button onClick={() => setSelected(event)}><BookOpen size={14}/>查看 {event.citations.length} 条证据</button><span>{interpretation ? `${interpretation.provider} / ${interpretation.model}` : "尚无模型解释"}</span></footer></div></article>})}</section>}
    {tab === "briefings" && bundle && <section className="briefing-ledger">{bundle.briefings.length === 0 ? <div className="news-empty"><FileSearch size={28}/><b>暂无冻结简报</b></div> : bundle.briefings.map((item) => <article key={item.report_id}><div><span>{phaseName[item.phase]}</span><time>{item.trading_date}</time></div><strong>{item.sections.watchlist.length} 个观察标的</strong><small>{item.event_ids.length} 个事件 · {item.interpretation_ids.length} 条解释</small><code>{item.input_snapshot_hash.slice(0, 16)}</code></article>)}</section>}
    {tab === "quality" && bundle && <section className="quality-console"><div><span>引用覆盖率</span><strong>{percent(bundle.quality.citation_coverage)}</strong><small>{bundle.quality.interpretation_count} 条解释</small></div><div><span>新闻重复率</span><strong>{percent(bundle.quality.duplicate_rate)}</strong><small>{bundle.quality.article_count} 篇原文 / {bundle.quality.cluster_count} 个事件簇</small></div><div><span>无效 JSON 率</span><strong>{percent(bundle.quality.invalid_json_rate)}</strong><small>模型结构校验</small></div><div><span>人工修正率</span><strong>{percent(bundle.quality.human_correction_rate)}</strong><small>{bundle.quality.correction_count} 条修正</small></div></section>}
    {selected && <div className="evidence-backdrop" onClick={() => setSelected(null)}><aside className="evidence-drawer" role="dialog" aria-label="事件证据" onClick={(event) => event.stopPropagation()}><header><div><p className="eyebrow">EVIDENCE CHAIN</p><h2>事件证据</h2></div><button aria-label="关闭证据" onClick={() => setSelected(null)}><X size={18}/></button></header><section><h3>来源引用</h3>{selected.citations.map((citation) => <a href={citation.canonical_url} target="_blank" rel="noreferrer" key={citation.citation_id}><span>{citation.publisher} · {new Date(citation.published_at).toLocaleString("zh-CN")}</span><p>{citation.quoted_text}</p><code>{citation.content_hash.slice(0, 16)}</code></a>)}</section>{contrary.length > 0 && <section className="contrary-evidence"><h3>相反证据</h3>{contrary.map((citation) => <p key={citation.citation_id}>{citation.quoted_text}</p>)}</section>}<section className="human-review"><h3>人工复核</h3><label>复核理由<textarea aria-label="复核理由" value={reason} onChange={(event) => setReason(event.target.value)}/></label><button disabled={saving || !reason.trim()} onClick={() => void saveCorrection()}><CheckCircle2 size={15}/>{saving ? "存档中" : "确认并存档"}</button></section></aside></div>}
  </main>;
}
