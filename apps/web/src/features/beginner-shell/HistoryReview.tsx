import { AlertTriangle, CalendarDays, Clock3, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Advice, DecisionPhase, DecisionResponse } from "../decision-workbench/types";
import { friendlyError } from "../../shared/friendlyError";

const phaseNames: Record<DecisionPhase, string> = { premarket: "盘前研判", intraday: "盘中观察", postclose: "盘后复盘" };
const actionNames: Record<Advice["action"], string> = { observe: "加入观察", wait: "暂不参与", avoid: "回避", invalidated: "已失效" };

export function HistoryReview({ loadCurrent, loadDate, symbol }: { loadCurrent: () => Promise<DecisionResponse>; loadDate?: (date: string) => Promise<DecisionResponse>; symbol: string | null }) {
  const [data, setData] = useState<DecisionResponse | null>(null); const [error, setError] = useState(""); const [date, setDate] = useState(""); const request = useRef(0);
  const load = useCallback(async (selected?: string) => { const current = ++request.current; setError(""); try { const next = selected && loadDate ? await loadDate(selected) : await loadCurrent(); if (current === request.current) { setData(next); setDate(next.trading_date); } } catch (reason) { if (current === request.current) setError(friendlyError(reason, "历史复盘")); } }, [loadCurrent, loadDate]);
  useEffect(() => { void load(); return () => { request.current += 1; }; }, [load]);
  return <main className="beginner-page history-review"><header><p className="eyebrow">历史复盘</p><h1>按日期查看判断变化</h1><p>只展示当时可见的结论、证据和风险。</p><label><CalendarDays size={16} />复盘日期<input aria-label="复盘日期" type="date" value={date} onChange={(event) => { setDate(event.target.value); void load(event.target.value); }} /></label></header>
    {error && <section className="beginner-empty" role="alert"><AlertTriangle /><h2>{error}</h2><button onClick={() => void load(date || undefined)}>重试</button></section>}
    {data && <><p className="history-date">{data.trading_date}{symbol ? ` · ${symbol}` : " · 尚未选择 A 股"}</p><div className="history-phases">{(["premarket", "intraday", "postclose"] as DecisionPhase[]).map((phase) => { const slot = data.phases[phase]; const items = slot.advice.filter((item) => !symbol || item.symbol === symbol); const item = items.at(-1); const phaseRan = slot.phase_status !== "empty" || slot.aggregate_version !== null; const emptyMessage = phaseRan ? (symbol ? "本阶段已运行，当时未纳入这只股票" : "本阶段已运行，没有可展示的 A 股") : "本阶段没有生成可核验记录"; return <section key={phase}><h2>{phaseNames[phase]}</h2>{!item ? <p>{emptyMessage}</p> : <><span>{actionNames[item.action]}</span><h3>{item.conclusion}</h3><p>{item.plain_language_explanation}</p>{item.supporting_evidence.slice(0, 3).map((evidence) => <p key={evidence.evidence_id}>{evidence.summary}</p>)}{item.risks.slice(0, 3).map((risk) => <p className="history-risk" key={risk}><ShieldAlert size={14} />{risk}</p>)}<time><Clock3 size={13} />{new Date(item.created_at).toLocaleString("zh-CN", { hour12: false })}</time></>}</section>; })}</div></>}
  </main>;
}
