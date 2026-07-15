import { AlertTriangle, CheckCircle2, Clock3, RefreshCw, ShieldAlert, Target, TrendingDown, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useSelectedInstrument } from "../instrument-selection/SelectedInstrumentProvider";
import type { Advice } from "../decision-workbench/types";
import type { StockCockpitSnapshot } from "./types";
import { CockpitSections } from "./CockpitSections";
import { PhaseTimeline } from "./PhaseTimeline";

type Loader = (symbol: string, asOf?: string, signal?: AbortSignal) => Promise<StockCockpitSnapshot>;
type Props = { load: Loader; asOf?: string; refreshToken?: number; onRefreshRequest?: () => void };

const qualityNames = { ready: "数据完整", partial: "部分可用", blocked: "数据已拦截" } as const;
const sectionQualityNames = { ready: "行情有效", partial: "行情部分可用", stale: "行情陈旧", unavailable: "行情不可用", blocked: "行情已拦截" } as const;

function metric(data: StockCockpitSnapshot, key: string): unknown {
  const metrics = data.sections.market?.payload.metrics as Record<string, unknown> | undefined;
  if (key === "latest_price") return metrics?.price ?? metrics?.latest_price;
  return metrics?.[key];
}
function displayNumber(value: unknown, suffix = ""): string {
  return value === null || value === undefined || value === "" ? "--" : `${String(value)}${suffix}`;
}
function currentAdvice(items: Advice[]): Advice | null {
  return [...items].sort((left, right) => {
    if (left.horizon !== right.horizon) return left.horizon === "intraday" ? -1 : 1;
    return Date.parse(right.created_at) - Date.parse(left.created_at);
  })[0] ?? null;
}

function planGateReady(advice: Advice): boolean {
  const gate = advice.simulation_gate;
  return advice.action === "simulated_plan" && Boolean(advice.simulation_plan_id) && Boolean(advice.risk_decision_id) && gate?.quote_state === "ready" && gate.compliance_state === "ready" && gate.evidence_state === "ready" && gate.risk_state === "approve" && gate.risk_decision_id === advice.risk_decision_id && Boolean(gate.compliance_snapshot_id);
}

function CandidateMembership({ memberships }: { memberships: StockCockpitSnapshot["candidate_membership"] }) {
  if (!memberships.length) return <span className="candidate-membership none">非当前候选</span>;
  return <div className="candidate-memberships">{memberships.includes("short_term") && <span>短线候选</span>}{memberships.includes("swing") && <span>波段候选</span>}</div>;
}

function AuthoritativePlan({ advice }: { advice: Advice }) {
  if (!planGateReady(advice)) return null;
  return <section className="authoritative-plan"><header><Target size={15} /><h3>模拟操作计划</h3></header><p>权威门禁已全部通过，当前接口仅提供不可变方案引用，不展示未返回的价格或仓位。</p><dl><div><dt>方案引用</dt><dd>{advice.simulation_plan_id}</dd></div><div><dt>风控决策</dt><dd>{advice.risk_decision_id}</dd></div><div><dt>合规快照</dt><dd>{advice.simulation_gate?.compliance_snapshot_id}</dd></div></dl></section>;
}

function AdviceConclusion({ advice, qualityReason }: { advice: Advice | null; qualityReason: string }) {
  if (!advice) return <section className="cockpit-conclusion empty"><header><p className="eyebrow">AI 解释 / 确定性规则</p><h2>当前判断</h2></header><div className="no-advice"><ShieldAlert size={20} /><div><b>当前没有可展示建议</b><p>{qualityReason}</p></div></div></section>;
  const readyPlan = planGateReady(advice);
  return <section className="cockpit-conclusion"><header><div><p className="eyebrow">AI 解释 / 确定性规则</p><h2>当前判断</h2></div><div className="advice-confidence"><span>确定性置信度</span><strong>{Math.round(Number(advice.confidence) * 100)}%</strong></div></header>
    <div className="advice-verdict"><div><span>{advice.horizon === "intraday" ? "盘中优先" : "波段观察"}</span><h3>{advice.conclusion}</h3><p>{advice.plain_language_explanation || "AI 解释暂不可用，保留确定性结论。"}</p></div><div className={readyPlan ? "observe-seal gate-ready" : "observe-seal"}>{readyPlan ? <CheckCircle2 size={18} /> : <ShieldAlert size={18} />}<b>{readyPlan ? "门禁通过" : "仅观察"}</b><small>{readyPlan ? "存在权威方案引用" : "未形成权威门禁方案"}</small></div></div>
    <div className="advice-evidence-grid">
      <section><h3><CheckCircle2 size={15} />支持证据</h3>{advice.supporting_evidence.length ? advice.supporting_evidence.map((item) => <p key={item.evidence_id}>{item.summary}<small>{item.source} · {new Date(item.observed_at).toLocaleString("zh-CN", { hour12: false })}</small></p>) : <p>暂无已验证支持证据</p>}</section>
      <section className="contrary"><h3><AlertTriangle size={15} />反方证据</h3>{advice.contrary_evidence.length ? advice.contrary_evidence.map((item) => <p key={item.evidence_id}>{item.summary}<small>{item.source} · {new Date(item.observed_at).toLocaleString("zh-CN", { hour12: false })}</small></p>) : <p>暂无已验证反方证据</p>}</section>
      <section className="risk"><h3><ShieldAlert size={15} />关键风险</h3>{advice.risks.length ? advice.risks.map((item) => <p key={item}>{item}</p>) : <p>当前记录未列出风险</p>}</section>
      <section><h3><Target size={15} />失效条件</h3>{advice.invalidation_conditions.length ? advice.invalidation_conditions.map((item) => <p key={item}>{item}</p>) : <p>当前记录未列出失效条件</p>}</section>
    </div>
    <AuthoritativePlan advice={advice} />
    <footer><span>建议时间：{new Date(advice.created_at).toLocaleString("zh-CN", { hour12: false })}</span><span>策略：{advice.strategy_version}</span></footer>
  </section>;
}

export function StockDecisionCockpit({ load, asOf, refreshToken = 0, onRefreshRequest }: Props) {
  const { symbol } = useSelectedInstrument();
  const [data, setData] = useState<StockCockpitSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const hasData = useRef(false);
  const loadedContext = useRef<string | null>(null);
  const contextKey = symbol ? `${symbol}:${asOf || "live"}` : null;

  const refresh = useCallback(async () => {
    if (!symbol) return;
    const request = ++generation.current;
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    setLoading(true); setError("");
    try {
      const next = await load(symbol, asOf || undefined, nextController.signal);
      if (request !== generation.current || nextController.signal.aborted) return;
      setData(next); loadedContext.current = contextKey; hasData.current = true; setStale(false);
    } catch (caught) {
      if (request !== generation.current || nextController.signal.aborted) return;
      setError(caught instanceof Error ? caught.message : "驾驶舱链路暂不可用");
      setStale(hasData.current);
    } finally { if (request === generation.current) setLoading(false); }
  }, [asOf, contextKey, load, symbol]);

  useEffect(() => {
    if (!symbol) { generation.current += 1; controller.current?.abort(); setData(null); loadedContext.current = null; hasData.current = false; setError(""); setStale(false); return; }
    if (loadedContext.current !== contextKey) { setData(null); loadedContext.current = null; hasData.current = false; setStale(false); }
    void refresh();
    return () => controller.current?.abort();
  }, [symbol, load, asOf, refreshToken]);

  if (!symbol) return <main className="stock-cockpit empty-cockpit"><Target size={24} /><h1>先选择一只 A 股</h1><p>从左侧候选池、自选或代码与名称搜索中选择，系统不会猜测股票。</p></main>;
  if (data && data.symbol !== symbol) return <main className="stock-cockpit cockpit-loading" aria-busy="true"><RefreshCw size={22} /><h1>正在切换股票</h1><p>{symbol}</p></main>;
  if (!data && loading) return <main className="stock-cockpit cockpit-loading" aria-busy="true"><RefreshCw size={22} /><h1>正在组装单股决策底稿</h1><p>{symbol}</p></main>;
  if (!data) return <main className="stock-cockpit cockpit-loading"><AlertTriangle size={22} /><h1>驾驶舱暂不可用</h1><p role="alert">{error}</p><button type="button" onClick={() => void refresh()}>重试</button></main>;

  const change = Number(metric(data, "change_percent"));
  const positive = Number.isFinite(change) && change >= 0;
  const advice = currentAdvice(data.current_advice);
  return <main className="stock-cockpit">
    <header className="cockpit-identity"><div><p className="eyebrow">A 股单股决策驾驶舱 / {data.instrument.exchange.toUpperCase()}</p><h1>{data.instrument.name} <span>{data.symbol}</span></h1><div className="cockpit-quote"><strong>{displayNumber(metric(data, "latest_price"))}</strong><span className={positive ? "positive" : "negative"}>{Number.isFinite(change) ? positive ? <TrendingUp size={15} /> : <TrendingDown size={15} /> : null}{displayNumber(metric(data, "change_percent"), "%")}</span></div><CandidateMembership memberships={data.candidate_membership} /></div>
      <div className="cockpit-quality"><div><Clock3 size={15} /><span>行情时间</span><b>{data.sections.market?.observed_at ? new Date(data.sections.market.observed_at).toLocaleString("zh-CN", { hour12: false }) : "未提供"}</b></div><div><span>快照质量</span><b>{qualityNames[data.overall_quality]}</b><small>{data.sections.market ? sectionQualityNames[data.sections.market.status] : "行情不可用"}</small></div><button type="button" aria-label="刷新驾驶舱" onClick={() => onRefreshRequest ? onRefreshRequest() : void refresh()} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""} /></button></div>
    </header>
    {error && <div className="cockpit-error" role="alert"><AlertTriangle size={16} /><span>{error}</span>{stale && <b>当前内容已陈旧</b>}</div>}
    <AdviceConclusion advice={advice} qualityReason={data.overall_quality === "blocked" ? "决策数据已被风控门禁拦截。" : "当前阶段尚未生成该股票的已验证建议。"} />
    <CockpitSections sections={data.sections} />
    <PhaseTimeline phases={data.phases} symbol={data.symbol} />
  </main>;
}
