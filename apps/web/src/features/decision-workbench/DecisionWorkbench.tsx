import { AlertTriangle, Bot, Clock3, RefreshCw, ShieldAlert, Target, Telescope } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { Advice, DecisionPhase, DecisionResponse, PhaseSlot, PlanReadiness, SimulationPlan } from "./types";

type Props = {
  loadCurrent: () => Promise<DecisionResponse>; loadDate?: (date: string) => Promise<DecisionResponse>;
  selectedSymbol?: string | null; asOf?: string; onAsOfChange?: (date: string) => void;
  refreshToken?: number; onRefresh?: (reason: "manual" | "poll") => void;
};
const phaseNames: Record<DecisionPhase, string> = { premarket: "盘前研判", intraday: "盘中监测", postclose: "盘后复盘" };
const actionNames: Record<Advice["action"], string> = { observe: "观察", wait: "等待", avoid: "回避", invalidated: "已失效", simulated_plan: "模拟计划" };

function ChangeStream({ slot }: { slot: PhaseSlot }) {
  if (!slot.change_stream?.length) return null;
  return <section className="change-stream" aria-label="盘中变化流"><h4>变化流</h4>{slot.change_stream.map((version) => <details key={version.snapshot_id} open><summary>变化版本 #{version.sequence} · {version.delta_advice.length} 项 · {new Date(version.generated_at).toLocaleTimeString("zh-CN")}</summary><div>{version.delta_advice.length === 0 ? <p>本版本没有建议字段变化</p> : version.delta_advice.map((advice) => <article key={advice.advice_id}><b>{advice.symbol} · {actionNames[advice.action]} · {advice.conclusion}</b><span>变更字段：{advice.changed_fields?.length ? advice.changed_fields.join("、") : "首次记录或未标注字段级变化"}</span><span>前序建议：{advice.previous_advice_id ?? "无（当前记录未提供前序）"}</span><div>{advice.supporting_evidence.length ? advice.supporting_evidence.map((evidence) => <p key={evidence.evidence_id}>触发证据：{evidence.summary}<small>{evidence.source} · {new Date(evidence.observed_at).toLocaleString("zh-CN")}</small></p>) : <p>确定性原因：{advice.risks.join("；") || advice.invalidation_conditions.join("；") || "当前记录未提供具体原因"}</p>}</div></article>)}</div></details>)}</section>;
}

function CompletePlan({ advice, plans, readiness }: { advice: Advice; plans: SimulationPlan[]; readiness?: PlanReadiness }) {
  const plan = plans.find((item) => item.plan_id === advice.simulation_plan_id && item.advice_id === advice.advice_id && item.risk_decision_id === advice.risk_decision_id);
  if (advice.action !== "simulated_plan" || !plan?.compliance_snapshot_id || !readiness?.ready) return <p className="observation-only">当前仅供观察，不形成模拟操作计划。</p>;
  return <section className="simulation-plan"><header><Target size={15} /><h4>模拟操作计划</h4></header><dl>
    <div><dt>观察区间</dt><dd>{plan.watch_price_low} - {plan.watch_price_high}</dd></div><div><dt>失效参考</dt><dd>{plan.stop_loss}</dd></div>
    <div><dt>最大模拟仓位</dt><dd>{plan.max_position}</dd></div><div><dt>目标观察</dt><dd>{plan.take_profit.join(" / ")}</dd></div>
  </dl><small>{plan.risk_version} · {plan.compliance_version}</small></section>;
}

function AdvicePanel({ advice, plans, readiness }: { advice: Advice; plans: SimulationPlan[]; readiness?: PlanReadiness }) {
  return <article className="decision-advice"><header><div><span>{advice.horizon === "intraday" ? "短期观察" : "波段观察"}</span><h3>{advice.symbol} · {advice.conclusion}</h3></div><strong>{Math.round(Number(advice.confidence) * 100)}%</strong></header>
    <p className="plain-explanation">{advice.plain_language_explanation || "AI 解释不可用，保留确定性结论。"}</p>
    <section className="evidence-band"><h4>支持证据</h4>{advice.supporting_evidence.map((item) => <p key={item.evidence_id}>{item.summary}<small>{item.source} · {new Date(item.observed_at).toLocaleString("zh-CN")}</small></p>)}</section>
    <section className="risk-band"><h4><ShieldAlert size={14} />关键风险</h4>{advice.risks.map((risk) => <p key={risk}>{risk}</p>)}</section>
    <section className="contrary-band"><h4><AlertTriangle size={14} />反向证据</h4>{advice.contrary_evidence.length ? advice.contrary_evidence.map((item) => <p key={item.evidence_id}>{item.summary}</p>) : <p>反向证据：暂无已验证记录</p>}</section>
    <section className="invalidation-band"><h4>失效条件</h4>{advice.invalidation_conditions.map((item) => <p key={item}>{item}</p>)}</section>
    <CompletePlan advice={advice} plans={plans} readiness={readiness} />
    <footer><span>来源时间 {new Date(advice.created_at).toLocaleString("zh-CN")}</span><code>{advice.strategy_version}</code></footer>
  </article>;
}

function PhaseContent({ slot, serverTime, staleAfter, pollingStatus, selectedSymbol }: { slot: PhaseSlot; serverTime: string; staleAfter: number; pollingStatus?: string; selectedSymbol?: string | null }) {
  if (slot.phase_status === "empty") return <section className="decision-message"><Telescope size={24} /><h2>{selectedSymbol === null ? "尚未选择 A 股，当前不展示单股记录" : selectedSymbol ? `${selectedSymbol} 当前阶段暂无决策快照` : "当前阶段暂无决策快照"}</h2><p>等待调度生成已验证的聚合结果，不展示推测数据。</p></section>;
  const stale = Boolean(slot.generated_at && Date.parse(serverTime) - Date.parse(slot.generated_at) > staleAfter * 1000);
  const emptyTitle = selectedSymbol === null ? "尚未选择 A 股，当前不展示单股建议" : selectedSymbol ? `${selectedSymbol} 当前阶段暂无已验证建议` : "当前阶段没有可展示建议";
  return <div className="decision-columns"><section><div className={`quality-banner ${slot.phase_status}`}><b>{slot.phase_status === "blocked" ? "决策已拦截" : slot.phase_status === "partial" ? "数据部分可用" : "决策快照就绪"}</b><span>{slot.aggregate_version}</span></div>{stale && <div className="stale-banner">聚合数据已过期</div>}{slot.advice.length === 0 && <section className="decision-message compact"><h2>{emptyTitle}</h2><p>保留阶段质量状态，不补造建议。</p></section>}{slot.advice.map((item) => <AdvicePanel key={item.advice_id} advice={item} plans={slot.plans} readiness={slot.plan_readiness[item.advice_id]} />)}</section><aside className="decision-rail"><h3>阶段状态</h3><p><Bot size={14} />AI {slot.ai_status === "ready" ? "可用" : slot.ai_status === "unavailable" ? "不可用" : "未调用"}</p><p>质量 {slot.quality}</p><p>轮询 {pollingStatus ?? "uninitialized"}</p><p>当前观察 {slot.advice.length} · 本次变化 {slot.delta_advice?.length ?? 0}</p><p>变化版本 {slot.delta_version ?? "--"}</p><p>聚合版本 {slot.aggregate_version}</p><ChangeStream slot={slot} /></aside></div>;
}

function selectedSlot(slot: PhaseSlot, symbol?: string | null): PhaseSlot {
  if (symbol === undefined) return slot;
  const advice = slot.advice.filter((item) => item.asset === "a_share" && item.symbol === symbol);
  const adviceIds = new Set(advice.map((item) => item.advice_id));
  const evidenceIds = new Set(advice.flatMap((item) => [...item.supporting_evidence, ...item.contrary_evidence]).map((item) => item.evidence_id));
  const plans = slot.plans.filter((item) => adviceIds.has(item.advice_id));
  const planIds = new Set(plans.map((item) => item.plan_id));
  const deltaAdvice = slot.delta_advice?.filter((item) => item.asset === "a_share" && item.symbol === symbol);
  const deltaAdviceIds = new Set(deltaAdvice?.map((item) => item.advice_id) ?? []);
  return {
    ...slot, advice, evidence: slot.evidence.filter((item) => evidenceIds.has(item.evidence_id)), plans,
    plan_readiness: Object.fromEntries(Object.entries(slot.plan_readiness).filter(([id]) => adviceIds.has(id))),
    delta_advice: deltaAdvice, delta_plans: slot.delta_plans?.filter((item) => planIds.has(item.plan_id) || deltaAdviceIds.has(item.advice_id)),
    change_stream: slot.change_stream?.map((version) => {
      const versionAdvice = version.delta_advice.filter((item) => item.asset === "a_share" && item.symbol === symbol);
      const versionIds = new Set(versionAdvice.map((item) => item.advice_id));
      return { ...version, delta_advice: versionAdvice, delta_plans: version.delta_plans.filter((item) => versionIds.has(item.advice_id)) };
    }).filter((version) => version.delta_advice.length > 0 || version.delta_plans.length > 0),
  };
}

export function DecisionWorkbench({ loadCurrent, loadDate, selectedSymbol, asOf, onAsOfChange, refreshToken = 0, onRefresh }: Props) {
  const [data, setData] = useState<DecisionResponse | null>(null); const [phase, setPhase] = useState<DecisionPhase>("premarket");
  const [internalDate, setInternalDate] = useState(""); const date = asOf ?? internalDate; const [error, setError] = useState(""); const [loading, setLoading] = useState(true); const sequence = useRef(0); const manualPhase = useRef(false); const initialLoad = useRef(true); const historicalMode = useRef(false); const handledRefresh = useRef(refreshToken);
  const publishDate = useCallback((nextDate: string) => { setInternalDate(nextDate); onAsOfChange?.(nextDate); }, [onAsOfChange]);
  const load = useCallback(async (selectedDate?: string) => { const request = ++sequence.current; setLoading(true); setError(""); try { const next = selectedDate && loadDate ? await loadDate(selectedDate) : await loadCurrent(); if (request !== sequence.current) return; setData(next); if (initialLoad.current || !manualPhase.current) setPhase(next.current_phase); initialLoad.current = false; publishDate(next.trading_date); } catch (caught) { if (request === sequence.current) setError(caught instanceof Error ? caught.message : "决策链路暂不可用"); } finally { if (request === sequence.current) setLoading(false); } }, [loadCurrent, loadDate, publishDate]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (refreshToken === handledRefresh.current) return; handledRefresh.current = refreshToken; void load(historicalMode.current ? date : undefined); }, [date, load, refreshToken]);
  useEffect(() => { if (!data || data.market_session !== "open" || !data.polling.focus_interval_seconds) return; const timer = window.setInterval(() => { if (onRefresh) onRefresh("poll"); else void load(historicalMode.current ? date : undefined); }, Math.max(1, data.polling.focus_interval_seconds) * 1000); return () => window.clearInterval(timer); }, [data?.market_session, data?.polling.focus_interval_seconds, date, load, onRefresh]);
  const phases = Object.keys(phaseNames) as DecisionPhase[];
  function selectPhase(item: DecisionPhase, focus = false) { manualPhase.current = true; if (focus) document.getElementById(`decision-tab-${item}`)?.focus(); setPhase(item); }
  function tabKey(event: React.KeyboardEvent, item: DecisionPhase) { const index = phases.indexOf(item); const next = event.key === "ArrowRight" ? phases[(index + 1) % phases.length] : event.key === "ArrowLeft" ? phases[(index - 1 + phases.length) % phases.length] : null; if (next) { event.preventDefault(); selectPhase(next, true); } }
  return <main className="decision-workbench"><header className="decision-header"><div><p className="eyebrow">A 股 · 每日决策工作台</p><h1>今日判断与三阶段跟踪</h1></div><div className="decision-date-controls"><label>交易日期<input aria-label="交易日期" type="date" value={date} onChange={(event) => { historicalMode.current = true; publishDate(event.target.value); void load(event.target.value); }} /></label><button type="button" onClick={() => onRefresh ? onRefresh("manual") : void load(historicalMode.current ? date : undefined)}><RefreshCw size={14} />刷新当前</button></div></header>
    {data && <section className="session-status"><div><Clock3 size={15} /><b>{data.market_session === "open" ? "市场进行中" : "市场已休市"}</b><span>焦点 {data.polling.focus_interval_seconds ?? "--"}s</span></div><div><span>全域 {data.polling.universe_interval_seconds ?? "--"}s</span><span>超时阈值 {data.polling.stale_after_seconds}s</span><span>下次检查 {data.polling.next_check_seconds ?? "--"}s</span></div></section>}
    <div className="phase-tabs" role="tablist">{phases.map((item) => <button id={`decision-tab-${item}`} aria-controls={`decision-panel-${item}`} tabIndex={phase === item ? 0 : -1} key={item} role="tab" aria-selected={phase === item} onKeyDown={(event) => tabKey(event, item)} onClick={() => selectPhase(item)}>{phaseNames[item]}</button>)}</div>
    {loading && !data && <section className="decision-message" aria-busy="true"><RefreshCw size={22} /><h2>正在读取决策聚合</h2></section>}
    {error && <section className="decision-error" role="alert"><AlertTriangle size={18} /><p>{error}</p><button onClick={() => void load(historicalMode.current ? date : undefined)}>重试</button></section>}
    {data && !error && <div id={`decision-panel-${phase}`} role="tabpanel" aria-labelledby={`decision-tab-${phase}`}><PhaseContent slot={selectedSlot(data.phases[phase], selectedSymbol)} serverTime={data.server_time} staleAfter={data.polling.stale_after_seconds} pollingStatus={data.polling.status} selectedSymbol={selectedSymbol} /></div>}
  </main>;
}
