import { AlertTriangle, Bot, Clock3, RefreshCw, ShieldAlert, Target, Telescope } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { Advice, DecisionPhase, DecisionResponse, PhaseSlot, SimulationPlan } from "./types";

type Props = { loadCurrent: () => Promise<DecisionResponse>; loadDate?: (date: string) => Promise<DecisionResponse> };
const phaseNames: Record<DecisionPhase, string> = { premarket: "盘前研判", intraday: "盘中监测", postclose: "盘后复盘" };

function CompletePlan({ advice, plans }: { advice: Advice; plans: SimulationPlan[] }) {
  const plan = plans.find((item) => item.plan_id === advice.simulation_plan_id && item.advice_id === advice.advice_id && item.risk_decision_id === advice.risk_decision_id);
  if (advice.action !== "simulated_plan" || !plan?.compliance_snapshot_id) return <p className="observation-only">当前仅供观察，不形成模拟操作计划。</p>;
  return <section className="simulation-plan"><header><Target size={15} /><h4>模拟操作计划</h4></header><dl>
    <div><dt>观察区间</dt><dd>{plan.watch_price_low} - {plan.watch_price_high}</dd></div><div><dt>失效参考</dt><dd>{plan.stop_loss}</dd></div>
    <div><dt>最大模拟仓位</dt><dd>{plan.max_position}</dd></div><div><dt>目标观察</dt><dd>{plan.take_profit.join(" / ")}</dd></div>
  </dl><small>{plan.risk_version} · {plan.compliance_version}</small></section>;
}

function AdvicePanel({ advice, plans }: { advice: Advice; plans: SimulationPlan[] }) {
  return <article className="decision-advice"><header><div><span>{advice.horizon === "intraday" ? "短期观察" : "波段观察"}</span><h3>{advice.symbol} · {advice.conclusion}</h3></div><strong>{Math.round(Number(advice.confidence) * 100)}%</strong></header>
    <p className="plain-explanation">{advice.plain_language_explanation || "AI 解释不可用，保留确定性结论。"}</p>
    <section className="evidence-band"><h4>支持证据</h4>{advice.supporting_evidence.map((item) => <p key={item.evidence_id}>{item.summary}<small>{item.source} · {new Date(item.observed_at).toLocaleString("zh-CN")}</small></p>)}</section>
    <section className="risk-band"><h4><ShieldAlert size={14} />关键风险</h4>{advice.risks.map((risk) => <p key={risk}>{risk}</p>)}</section>
    <section className="contrary-band"><h4><AlertTriangle size={14} />反向证据</h4>{advice.contrary_evidence.length ? advice.contrary_evidence.map((item) => <p key={item.evidence_id}>{item.summary}</p>) : <p>反向证据：暂无已验证记录</p>}</section>
    <section className="invalidation-band"><h4>失效条件</h4>{advice.invalidation_conditions.map((item) => <p key={item}>{item}</p>)}</section>
    <CompletePlan advice={advice} plans={plans} />
    <footer><span>来源时间 {new Date(advice.created_at).toLocaleString("zh-CN")}</span><code>{advice.strategy_version}</code></footer>
  </article>;
}

function PhaseContent({ slot }: { slot: PhaseSlot }) {
  if (slot.phase_status === "empty") return <section className="decision-message"><Telescope size={24} /><h2>当前阶段暂无决策快照</h2><p>等待调度生成已验证的聚合结果，不展示推测数据。</p></section>;
  return <div className="decision-columns"><section><div className={`quality-banner ${slot.phase_status}`}><b>{slot.phase_status === "blocked" ? "决策已拦截" : slot.phase_status === "partial" ? "数据部分可用" : "决策快照就绪"}</b><span>{slot.aggregate_version}</span></div>{slot.advice.map((item) => <AdvicePanel key={item.advice_id} advice={item} plans={slot.plans} />)}</section><aside className="decision-rail"><h3>阶段状态</h3><p><Bot size={14} />AI {slot.ai_status === "ready" ? "可用" : slot.ai_status === "unavailable" ? "不可用" : "未调用"}</p><p>质量 {slot.quality}</p><p>版本 {slot.aggregate_version}</p></aside></div>;
}

export function DecisionWorkbench({ loadCurrent, loadDate }: Props) {
  const [data, setData] = useState<DecisionResponse | null>(null); const [phase, setPhase] = useState<DecisionPhase>("premarket");
  const [date, setDate] = useState(""); const [error, setError] = useState(""); const [loading, setLoading] = useState(true); const sequence = useRef(0);
  const load = useCallback(async (selectedDate?: string) => { const request = ++sequence.current; setLoading(true); setError(""); try { const next = selectedDate && loadDate ? await loadDate(selectedDate) : await loadCurrent(); if (request !== sequence.current) return; setData(next); setPhase(next.current_phase); setDate(next.trading_date); } catch (caught) { if (request === sequence.current) setError(caught instanceof Error ? caught.message : "决策链路暂不可用"); } finally { if (request === sequence.current) setLoading(false); } }, [loadCurrent, loadDate]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (!data || data.market_session !== "open") return; const timer = window.setInterval(() => void load(date), Math.max(1, data.polling.focus_interval_seconds) * 1000); return () => window.clearInterval(timer); }, [data?.market_session, data?.polling.focus_interval_seconds, date, load]);
  return <main className="decision-workbench"><header className="decision-header"><div><p className="eyebrow">A 股 · 每日决策工作台</p><h1>今日判断与三阶段跟踪</h1></div><label>交易日期<input aria-label="交易日期" type="date" value={date} onChange={(event) => { setDate(event.target.value); void load(event.target.value); }} /></label></header>
    {data && <section className="session-status"><div><Clock3 size={15} /><b>{data.market_session === "open" ? "市场进行中" : "市场已休市"}</b><span>聚合刷新 {data.polling.focus_interval_seconds}s</span></div><div><span>全域轮询 {data.polling.universe_interval_seconds}s</span><span>超时阈值 {data.polling.stale_after_seconds}s</span><span>下次检查 {data.polling.next_check_seconds ?? "--"}s</span></div></section>}
    <div className="phase-tabs" role="tablist">{(Object.keys(phaseNames) as DecisionPhase[]).map((item) => <button key={item} role="tab" aria-selected={phase === item} onClick={() => setPhase(item)}>{phaseNames[item]}</button>)}</div>
    {loading && !data && <section className="decision-message" aria-busy="true"><RefreshCw size={22} /><h2>正在读取决策聚合</h2></section>}
    {error && <section className="decision-error" role="alert"><AlertTriangle size={18} /><p>{error}</p><button onClick={() => void load(date || undefined)}>重试</button></section>}
    {data && !error && <PhaseContent slot={data.phases[phase]} />}
  </main>;
}
