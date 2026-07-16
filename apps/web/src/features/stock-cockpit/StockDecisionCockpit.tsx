import { AlertTriangle, CheckCircle2, Clock3, Database, RefreshCw, ShieldAlert, Target, TrendingDown, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useSelectedInstrument } from "../instrument-selection/SelectedInstrumentProvider";
import { friendlyError } from "../../shared/friendlyError";
import { isAutoSyncEnabled } from "../data-settings/DataSettingsView";
import type { AssessmentAIExplanation, AssessmentAIStatus, StockAssessment, StockCockpitSnapshot } from "./types";
import { CockpitSections } from "./CockpitSections";
import { PhaseTimeline } from "./PhaseTimeline";

type Loader = (symbol: string, asOf?: string, signal?: AbortSignal) => Promise<StockCockpitSnapshot>;
type Preparer = (symbol: string, signal?: AbortSignal) => Promise<import("./types").StockPreparation>;
type Props = { load: Loader; prepare?: Preparer; asOf?: string; refreshToken?: number; onRefreshRequest?: () => void; onSnapshot?: (snapshot: StockCockpitSnapshot) => void };

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
function AssessmentAI({ status, explanation }: { status: AssessmentAIStatus; explanation: AssessmentAIExplanation | null }) {
  if (status === "unconfigured") return <section className="assessment-ai"><h3>AI 补充分析未启用</h3><p>当前行动结论仍由可验证数据生成，可在“数据设置”中配置 AI。</p></section>;
  if (status !== "ready" || !explanation) return <section className="assessment-ai"><h3>AI 解释暂不可用</h3><p>确定性研判未受影响。</p></section>;
  return <section className="assessment-ai"><h3>AI 补充解释</h3><p>{explanation.plain_language}</p><dl><div><dt>新闻影响</dt><dd>{explanation.news_impact}</dd></div><div><dt>热点归因</dt><dd>{explanation.hotspot_attribution}</dd></div><div><dt>不确定性</dt><dd>{explanation.uncertainty}</dd></div><div><dt>反方观点</dt><dd>{explanation.contrary_view}</dd></div></dl><small>仅解释冻结证据，不改变确定性动作、置信度或方案资格。</small></section>;
}

function AssessmentConclusion({ assessment, aiStatus, aiExplanation }: { assessment: StockAssessment; aiStatus: AssessmentAIStatus; aiExplanation: AssessmentAIExplanation | null }) {
  const actionName = { observe: "加入观察", wait: "暂不参与", avoid: "回避" }[assessment.action];
  const evidence = assessment.supporting_evidence.slice(0, 3);
  const risks = [...assessment.contrary_evidence.map((item) => item.summary), ...assessment.risks].slice(0, 3);
  return <section className={`cockpit-conclusion assessment-conclusion action-${assessment.action}`}><header><div><p className="eyebrow">新手行动卡</p><h2>现在怎么做</h2></div><div className="advice-confidence"><span>置信度</span><strong>{Math.round(Number(assessment.confidence) * 100)}%</strong></div></header>
    <div className="advice-verdict"><div><span>{actionName}</span><h3>{assessment.conclusion}</h3><p>只根据截止时间前可验证的数据判断，不包含价格、仓位或买卖指令。</p></div><div className="observe-seal"><ShieldAlert size={18} /><b>观察提示</b><small>不构成投资建议</small></div></div>
    <AssessmentAI status={aiStatus} explanation={aiExplanation} />
    <div className="advice-evidence-grid">
      <section><h3><CheckCircle2 size={15} />主要依据</h3>{evidence.length ? evidence.map((item) => <p key={item.evidence_id}>{item.summary}</p>) : <p>暂缺足够的已验证依据</p>}</section>
      <section className="risk"><h3><ShieldAlert size={15} />主要风险</h3>{risks.length ? risks.map((item) => <p key={item}>{item}</p>) : <p>未发现明确风险，但仍需持续观察</p>}</section>
      <section><h3><Clock3 size={15} />需要等待的信号</h3><p>{assessment.action === "observe" ? "观察量价、趋势和新闻是否继续相互印证" : "等待缺失数据补齐，或风险信号减弱"}</p></section>
      <section><h3><Target size={15} />重新判断条件</h3>{assessment.invalidation_conditions.length ? assessment.invalidation_conditions.slice(0, 3).map((item) => <p key={item}>{item}</p>) : <p>出现新的行情、公告或风险证据时重新判断</p>}</section>
    </div>
    <footer><span>研判时间：{new Date(assessment.generated_at).toLocaleString("zh-CN", { hour12: false })}</span></footer>
  </section>;
}

function PreparationStatus({ data, preparing = false }: { data: StockCockpitSnapshot; preparing?: boolean }) {
  const fallbackSources = [
    ["quote", "market"], ["history", "trend"], ["finance", "fundamentals"], ["news", "news"],
  ].map(([name, section]) => ({
    name: name as "quote" | "history" | "finance" | "news",
    status: data.sections[section]?.status === "ready" ? "ready" as const : "partial" as const,
    observed_at: data.sections[section]?.observed_at ?? null,
    reason: data.sections[section]?.reason ?? null,
  }));
  const preparation = data.preparation ?? {
    symbol: data.symbol, status: fallbackSources.every((source) => source.status === "ready") ? "ready" as const : "partial" as const,
    sources: fallbackSources, refreshed: false, started_at: data.cutoff, completed_at: data.cutoff,
  };
  const ready = preparation.sources.filter((source) => source.status === "ready").length;
  const names = { quote: "实时行情", history: "历史走势", finance: "基本面", news: "新闻" } as const;
  const title = preparing ? "正在补齐数据" : !data.preparation ? "根据现有数据估算" : preparation.status === "ready" ? "数据已准备" : "部分数据待补齐";
  return <section className={`preparation-status ${preparation.status}`} aria-label="数据准备状态"><div><Database size={17} /><span><b>{title}</b><small>{preparation.refreshed ? "已自动检查并更新" : data.preparation ? "尚未执行自动补齐" : "已根据当前数据分区检查可用性"}</small></span></div><div className="preparation-sources">{preparation.sources.map((source) => <span className={source.status} key={source.name}>{names[source.name]}<b>{source.status === "ready" ? "可用" : "待补齐"}</b></span>)}</div><small>{ready}/{preparation.sources.length} 类核心数据可用</small></section>;
}

export function StockDecisionCockpit({ load, prepare, asOf, refreshToken = 0, onRefreshRequest, onSnapshot }: Props) {
  const { symbol } = useSelectedInstrument();
  const [data, setData] = useState<StockCockpitSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const hasData = useRef(false);
  const loadedContext = useRef<string | null>(null);
  const preparedContext = useRef<string | null>(null);
  const contextKey = symbol ? `${symbol}:${asOf || "live"}` : null;
  const loadRef = useRef(load); const prepareRef = useRef(prepare); const snapshotRef = useRef(onSnapshot);
  loadRef.current = load; prepareRef.current = prepare; snapshotRef.current = onSnapshot;

  const refresh = useCallback(async () => {
    if (!symbol) return;
    const request = ++generation.current;
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    setLoading(true); setError("");
    try {
      const next = await loadRef.current(symbol, asOf || undefined, nextController.signal);
      if (request !== generation.current || nextController.signal.aborted) return;
      setData(next); snapshotRef.current?.(next); loadedContext.current = contextKey; hasData.current = true; setStale(false);
      if (!asOf && prepareRef.current && next.preparation?.status !== "ready" && isAutoSyncEnabled() && preparedContext.current !== contextKey) {
        preparedContext.current = contextKey; setPreparing(true);
        try {
          const report = await prepareRef.current(symbol, nextController.signal);
          if (request !== generation.current || nextController.signal.aborted) return;
          setData((current) => current ? { ...current, preparation: report } : current);
          if (report.refreshed) {
            const refreshed = await loadRef.current(symbol, undefined, nextController.signal);
            if (request !== generation.current || nextController.signal.aborted) return;
            setData(refreshed); snapshotRef.current?.(refreshed);
          }
        } catch (caught) {
          if (request === generation.current && !nextController.signal.aborted) setError(friendlyError(caught, "数据同步"));
        } finally { if (request === generation.current) setPreparing(false); }
      }
    } catch (caught) {
      if (request !== generation.current || nextController.signal.aborted) return;
      setError(friendlyError(caught, "股票分析"));
      setStale(hasData.current);
    } finally { if (request === generation.current) setLoading(false); }
  }, [asOf, contextKey, symbol]);

  useEffect(() => {
    if (!symbol) { generation.current += 1; controller.current?.abort(); setData(null); loadedContext.current = null; preparedContext.current = null; hasData.current = false; setError(""); setStale(false); return; }
    if (loadedContext.current !== contextKey) { setData(null); loadedContext.current = null; preparedContext.current = null; hasData.current = false; setStale(false); }
    void refresh();
    return () => controller.current?.abort();
  }, [contextKey, refresh, refreshToken, symbol]);

  if (!symbol) return <main className="stock-cockpit empty-cockpit"><Target size={24} /><h1>先选择一只 A 股</h1><p>从左侧候选池、自选或代码与名称搜索中选择，系统不会猜测股票。</p></main>;
  if (data && data.symbol !== symbol) return <main className="stock-cockpit cockpit-loading" aria-busy="true"><RefreshCw size={22} /><h1>正在切换股票</h1><p>{symbol}</p></main>;
  if (!data && loading) return <main className="stock-cockpit cockpit-loading" aria-busy="true"><RefreshCw size={22} /><h1>正在组装单股决策底稿</h1><p>{symbol}</p></main>;
  if (!data) return <main className="stock-cockpit cockpit-loading"><AlertTriangle size={22} /><h1>驾驶舱暂不可用</h1><p role="alert">{error}</p><button type="button" onClick={() => void refresh()}>重试</button></main>;

  const change = Number(metric(data, "change_percent"));
  const positive = Number.isFinite(change) && change >= 0;
  return <main className="stock-cockpit">
    <header className="cockpit-identity"><div><p className="eyebrow">A 股观察 / {data.instrument.exchange.toUpperCase()}</p><h1>{data.instrument.name} <span>{data.symbol}</span></h1><div className="cockpit-quote"><strong>{displayNumber(metric(data, "latest_price"))}</strong><span className={positive ? "positive" : "negative"}>{Number.isFinite(change) ? positive ? <TrendingUp size={15} /> : <TrendingDown size={15} /> : null}{displayNumber(metric(data, "change_percent"), "%")}</span></div></div>
      <div className="cockpit-quality"><div><Clock3 size={15} /><span>行情时间</span><b>{data.sections.market?.observed_at ? new Date(data.sections.market.observed_at).toLocaleString("zh-CN", { hour12: false }) : "未提供"}</b></div><div><span>快照质量</span><b>{qualityNames[data.overall_quality]}</b><small>{data.sections.market ? sectionQualityNames[data.sections.market.status] : "行情不可用"}</small></div><button type="button" aria-label="刷新驾驶舱" onClick={() => onRefreshRequest ? onRefreshRequest() : void refresh()} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""} /></button></div>
    </header>
    {error && <div className="cockpit-error" role="alert"><AlertTriangle size={16} /><span>{error}</span>{stale && <b>当前内容已陈旧</b>}</div>}
    <PreparationStatus data={data} preparing={preparing} />
    <AssessmentConclusion assessment={data.assessment} aiStatus={data.ai_status} aiExplanation={data.ai_explanation} />
    <PhaseTimeline phases={data.phases} symbol={data.symbol} />
    <CockpitSections sections={data.sections} />
  </main>;
}
