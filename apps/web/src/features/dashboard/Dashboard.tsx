import { type ComponentProps, FormEvent, useCallback, useEffect, useState } from "react";
import {
  Activity, Archive, BarChart3, BookOpenCheck, Boxes, BriefcaseBusiness, Building2,
  ChevronRight, CircleDollarSign, Database, Gauge, Landmark, Radar, Search,
  RefreshCw, ShieldAlert, ShieldCheck, Siren, Workflow,
} from "lucide-react";

import { DataStatusPanel } from "../data-status/DataStatusPanel";
import type { DataStatusState, SyncReport } from "../data-status/types";
import { BacktestPanel } from "../backtest/BacktestPanel";
import type { BacktestResult } from "../backtest/types";
import type { ResearchCard } from "./types";
import { GovernanceView, type AuditStatus, type ComplianceStatus, type RiskStatus } from "../governance/GovernanceViews";
import { ConvertibleBondView } from "../convertible-bonds/ConvertibleBondView";
import type { BondCandidates, BondDashboard, BondDiagnosis } from "../convertible-bonds/types";
import { NewsIntelligenceView } from "../news-intelligence/NewsIntelligenceView";
import type { CorrectionInput, NewsIntelligenceBundle } from "../news-intelligence/types";
import { OperationsView } from "../operations/OperationsView";
import type { BackupRecord, BackupVerification, OperationsStatus } from "../operations/types";
import { AShareResearchView } from "../a-shares/AShareResearchView";
import type { AShareDiagnosis, CandidateBoard } from "../a-shares/types";
import { DecisionWorkbench } from "../decision-workbench/DecisionWorkbench";
import type { DecisionResponse } from "../decision-workbench/types";
import { StockSelector } from "../stock-cockpit/StockSelector";
import { StockDecisionCockpit } from "../stock-cockpit/StockDecisionCockpit";
import type { InstrumentSearchResponse, StockCockpitSnapshot } from "../stock-cockpit/types";
import { commitLocation } from "../instrument-selection/location";
import { useOptionalSelectedInstrument, useSelectedInstrument } from "../instrument-selection/SelectedInstrumentProvider";
import { BeginnerNavigation, type BeginnerView } from "../beginner-shell/BeginnerNavigation";
import { BeginnerRiskView } from "../beginner-shell/BeginnerRiskView";
import { HistoryReview } from "../beginner-shell/HistoryReview";
import { DataSettingsView } from "../data-settings/DataSettingsView";
import type { AISettingsDeleter, AISettingsLoader, AISettingsSaver, PreparationLoader } from "../data-settings/types";

type ViewState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; card: ResearchCard }
  | { kind: "error"; message: string };

type Props = {
  loadSnapshot: (symbol: string) => Promise<ResearchCard>;
  syncHistory?: (symbol: string, limit?: number) => Promise<SyncReport>;
  runBacktest?: (symbol: string, signal?: AbortSignal) => Promise<BacktestResult>;
  loadRisk?: () => Promise<RiskStatus>; loadCompliance?: (asset?: "a_share" | "convertible_bond") => Promise<ComplianceStatus>; loadAudit?: () => Promise<AuditStatus>;
  complianceAction?: (source: string, action: "authorize" | "revoke" | "acknowledge", permissionReference?: string, asset?: "a_share" | "convertible_bond") => Promise<unknown>;
  loadBondDashboard?: () => Promise<BondDashboard>;
  loadBondDiagnosis?: (code: string) => Promise<BondDiagnosis>;
  loadBondCandidates?: (filters?: Record<string, string>) => Promise<BondCandidates>;
  loadNewsIntelligence?: () => Promise<NewsIntelligenceBundle>;
  syncNews?: () => Promise<Record<string, number>>;
  createNewsCorrection?: (input: CorrectionInput) => Promise<unknown>;
  loadOperationsStatus?: () => Promise<OperationsStatus>;
  setSchedulerPaused?: (paused: boolean) => Promise<OperationsStatus["scheduler"]>;
  createBackup?: () => Promise<BackupRecord>;
  verifyBackup?: (backupId: string) => Promise<BackupVerification>;
  runManualJob?: (phase: string, tradingDate: string) => Promise<{ report_id: string }>;
  loadAShareCandidates?: () => Promise<CandidateBoard>;
  loadAShareDiagnosis?: (symbol: string, asOf?: string) => Promise<AShareDiagnosis>;
  loadDecisionCurrent?: () => Promise<DecisionResponse>;
  loadDecisionDate?: (date: string) => Promise<DecisionResponse>;
  searchAShareInstruments?: (query: string) => Promise<InstrumentSearchResponse>;
  loadStockCockpit?: (symbol: string, asOf?: string, signal?: AbortSignal) => Promise<StockCockpitSnapshot>;
  prepareStockData?: PreparationLoader;
  loadAISettings?: AISettingsLoader;
  saveAISettings?: AISettingsSaver;
  deleteAISettings?: AISettingsDeleter;
};

type ActiveView = BeginnerView;

export function preparationForSymbol(snapshot: StockCockpitSnapshot | null, symbol: string | null) {
  return snapshot?.symbol === symbol ? snapshot.preparation ?? null : null;
}

function viewFromPath(path: string): ActiveView {
  if (path === "/a-shares") return "a_shares";
  if (path === "/convertible-bonds") return "bonds";
  if (path === "/news-intelligence") return "news";
  if (path === "/risk") return "risk";
  if (path === "/history") return "history";
  if (path === "/settings") return "settings";
  return "dashboard";
}

const sourceNames: Record<string, string> = { tencent: "腾讯行情" };

function formatObservedAt(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(value));
}

function ResearchPanel({ card }: { card: ResearchCard }) {
  const blocked = card.action === "blocked";
  const positive = Number(card.change_percent) >= 0;
  return (
    <section className={`research-panel ${blocked ? "is-blocked" : "is-ready"}`}>
      <div className="panel-heading">
        <div>
          <p className="eyebrow">A 股 / 实时快照</p>
          <div className="symbol-line">
            <h2>{card.symbol}</h2>
            <span className={`change ${positive ? "positive" : "negative"}`}>
              {positive ? "+" : ""}{card.change_percent}%
            </span>
          </div>
        </div>
        <div className={`decision-state ${blocked ? "blocked" : "ready"}`} role="status">
          {blocked ? <ShieldAlert size={16} /> : <ShieldCheck size={16} />}
          {blocked ? "仅观察" : "数据有效"}
        </div>
      </div>
      <div className="evidence-grid">
        {card.evidence.map((item) => (
          <article className="evidence-item" key={`${item.label}-${item.observed_at}`}>
            <p>{item.label}</p><strong>{item.value}</strong>
            <div className="evidence-meta">
              <span>{sourceNames[item.source] ?? item.source}</span>
              <span>数据截至 {formatObservedAt(item.observed_at)}</span>
            </div>
          </article>
        ))}
        <article className="evidence-item muted-item">
          <p>结论等级</p><strong>{blocked ? "信号拦截" : "行情观察"}</strong>
          <div className="evidence-meta"><span>不构成买卖建议</span></div>
        </article>
      </div>
      {card.invalid_reasons.length > 0 && (
        <div className="risk-notice">
          <ShieldAlert size={18} />
          <div><b>风险规则已拦截</b>{card.invalid_reasons.map((reason) => <p key={reason}>{reason}</p>)}</div>
        </div>
      )}
    </section>
  );
}

function CoordinatedStockWorkbench({ loadCockpit, loadCurrent, loadDate }: {
  loadCockpit?: (symbol: string, asOf?: string, signal?: AbortSignal) => Promise<StockCockpitSnapshot>;
  loadCurrent: () => Promise<DecisionResponse>; loadDate?: (date: string) => Promise<DecisionResponse>;
}) {
  const { symbol } = useSelectedInstrument();
  const [displayAsOf, setDisplayAsOf] = useState("");
  const [historicalAsOf, setHistoricalAsOf] = useState<string | undefined>();
  const [refreshToken, setRefreshToken] = useState(0);
  const selectHistory = useCallback((date: string) => { setDisplayAsOf(date); setHistoricalAsOf(date); }, []);
  const resolveDate = useCallback((date: string) => setDisplayAsOf(date), []);
  const returnLive = useCallback(() => setHistoricalAsOf(undefined), []);
  const refreshBoth = useCallback(() => setRefreshToken((value) => value + 1), []);
  return <div className="stock-workbench-main">
    {loadCockpit && <StockDecisionCockpit load={loadCockpit} asOf={historicalAsOf} refreshToken={refreshToken} onRefreshRequest={refreshBoth} />}
    <DecisionWorkbench loadCurrent={loadCurrent} loadDate={loadDate} selectedSymbol={symbol} asOf={displayAsOf} onAsOfChange={selectHistory} onResolvedAsOf={resolveDate} onReturnLive={returnLive} refreshToken={refreshToken} onRefresh={refreshBoth} />
  </div>;
}

function SelectedNewsWorkspace({ loadBundle, syncNews, createCorrection, openNewsCompliance }: {
  loadBundle: () => Promise<NewsIntelligenceBundle>; syncNews: () => Promise<Record<string, number>>;
  createCorrection: (input: CorrectionInput) => Promise<unknown>; openNewsCompliance: () => void;
}) {
  const { symbol } = useSelectedInstrument();
  return <NewsIntelligenceView selectedSymbol={symbol} loadBundle={loadBundle} syncNews={syncNews} createCorrection={createCorrection} openNewsCompliance={openNewsCompliance} />;
}

function SelectedGovernanceWorkspace(props: ComponentProps<typeof GovernanceView>) {
  const symbol = useOptionalSelectedInstrument()?.symbol ?? null;
  return <div className="selected-governance-workspace"><div className="selected-symbol-context"><b>全局 / 资产级治理数据</b><span>不按单股过滤{symbol ? ` · 导航代码 ${symbol}` : ""}</span></div><GovernanceView {...props} /></div>;
}

function SelectedBacktestWorkspace({ runBacktest }: { runBacktest: (symbol: string, signal?: AbortSignal) => Promise<BacktestResult> }) {
  const { symbol } = useSelectedInstrument();
  return <main className="command-center"><BacktestPanel symbol={symbol ?? ""} runBacktest={runBacktest} /></main>;
}

export function Dashboard({ loadSnapshot, syncHistory, runBacktest, loadRisk, loadCompliance, loadAudit, complianceAction, loadBondDashboard, loadBondDiagnosis, loadBondCandidates, loadNewsIntelligence, syncNews, createNewsCorrection, loadOperationsStatus, setSchedulerPaused, createBackup, verifyBackup, runManualJob, loadAShareCandidates, loadAShareDiagnosis, loadDecisionCurrent, loadDecisionDate, searchAShareInstruments, loadStockCockpit, prepareStockData, loadAISettings, saveAISettings, deleteAISettings }: Props) {
  const selectedInstrument = useOptionalSelectedInstrument();
  const [state, setState] = useState<ViewState>({ kind: "idle" });
  const [symbol, setSymbol] = useState("600000");
  const [dataState, setDataState] = useState<DataStatusState>({ kind: "idle" });
  const [activeView, setActiveView] = useState<ActiveView>(viewFromPath(window.location.pathname));
  const [cockpitRefreshToken, setCockpitRefreshToken] = useState(0);
  const [latestCockpit, setLatestCockpit] = useState<StockCockpitSnapshot | null>(null);
  const selectedSymbol = selectedInstrument?.symbol ?? selectedInstrument?.lastSymbol ?? null;
  useEffect(() => { if (latestCockpit && latestCockpit.symbol !== selectedSymbol) setLatestCockpit(null); }, [latestCockpit, selectedSymbol]);
  useEffect(() => {
    const syncPath = () => setActiveView(viewFromPath(window.location.pathname));
    window.addEventListener("popstate", syncPath);
    return () => window.removeEventListener("popstate", syncPath);
  }, []);
  function navigate(view: ActiveView) {
    const paths: Record<ActiveView, string> = { dashboard: "/", a_shares: "/a-shares", risk: "/risk", history: "/history", settings: "/settings", bonds: "/convertible-bonds", news: "/news-intelligence" };
    const next = new URL(paths[view], window.location.origin);
    const selectedSymbol = new URL(window.location.href).searchParams.get("symbol") ?? selectedInstrument?.lastSymbol;
    if (view !== "bonds" && selectedSymbol) next.searchParams.set("symbol", selectedSymbol);
    commitLocation(`${next.pathname}${next.search}`);
    setActiveView(view);
  }

  async function inspect(requestedSymbol: string) {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", card: await loadSnapshot(requestedSymbol) });
    } catch (error) {
      setState({ kind: "error", message: error instanceof Error ? error.message : "未知错误" });
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void inspect(symbol);
  }

  async function syncDailyBars() {
    if (!syncHistory) return;
    setDataState({ kind: "syncing" });
    try {
      const report = await syncHistory(symbol, 250);
      if (report.state === "ready") setDataState({ kind: "ready", report });
      else setDataState({ kind: "error", message: report.message });
    } catch (error) {
      setDataState({ kind: "error", message: error instanceof Error ? error.message : "未知错误" });
    }
  }

  return (
    <div className="app-shell">
      <BeginnerNavigation active={activeView} onNavigate={navigate} />

      {activeView === "risk" && <BeginnerRiskView load={loadRisk} />}

      {activeView === "a_shares" && <div className="stock-workbench-layout observation-workspace">
        {loadAShareCandidates && searchAShareInstruments && <StockSelector loadCandidates={loadAShareCandidates} search={searchAShareInstruments} />}
        {loadStockCockpit ? <StockDecisionCockpit load={loadStockCockpit} prepare={prepareStockData} refreshToken={cockpitRefreshToken} onSnapshot={setLatestCockpit} /> : <main className="stock-cockpit empty-cockpit"><Radar size={24} /><h1>选择股票后查看行动卡</h1><p>可从候选、自选或搜索结果中选择任意已验证 A 股。</p></main>}
      </div>}

      {activeView === "bonds" && loadBondDashboard && loadBondDiagnosis && loadBondCandidates && <ConvertibleBondView loadDashboard={loadBondDashboard} loadDiagnosis={loadBondDiagnosis} loadCandidates={loadBondCandidates} openBondCompliance={() => undefined} />}

      {activeView === "news" && loadNewsIntelligence && syncNews && createNewsCorrection && <SelectedNewsWorkspace loadBundle={loadNewsIntelligence} syncNews={syncNews} createCorrection={createNewsCorrection} openNewsCompliance={() => undefined} />}

      {activeView === "history" && loadDecisionCurrent && <HistoryReview loadCurrent={loadDecisionCurrent} loadDate={loadDecisionDate} symbol={selectedInstrument?.symbol ?? selectedInstrument?.lastSymbol ?? null} />}

      {activeView === "settings" && loadAISettings && saveAISettings && deleteAISettings && <DataSettingsView loadAI={loadAISettings} saveAI={saveAISettings} deleteAI={deleteAISettings} symbol={selectedSymbol} prepare={prepareStockData} preparation={preparationForSymbol(latestCockpit, selectedSymbol)} onAIChanged={() => setCockpitRefreshToken((value) => value + 1)} />}
      {activeView === "settings" && (!loadAISettings || !saveAISettings || !deleteAISettings) && <main className="beginner-page"><header><p className="eyebrow">数据设置</p><h1>数据源与 AI</h1><p>设置服务暂不可用，请检查本地服务后重试。</p></header></main>}

      {activeView === "dashboard" && loadDecisionCurrent && <div className="stock-workbench-layout">
        {loadAShareCandidates && searchAShareInstruments && <StockSelector loadCandidates={loadAShareCandidates} search={searchAShareInstruments} />}
        {loadStockCockpit && <StockDecisionCockpit load={loadStockCockpit} prepare={prepareStockData} refreshToken={cockpitRefreshToken} onSnapshot={setLatestCockpit} />}
      </div>}

      {activeView === "dashboard" && !loadDecisionCurrent && <main className="command-center beginner-fallback">
        <header className="topbar">
          <div><p className="eyebrow">今日研判</p><h1>A 股观察</h1></div>
          <div className="system-state"><span className="pulse-dot" /><div><b>公开数据链路</b><small>等待选择股票</small></div></div>
        </header>
        <section className="mission-strip" aria-label="每日研究流程">
          <div className="mission active"><span>01</span><div><b>盘前研判</b><small>情报聚合 / 候选生成</small></div></div>
          <ChevronRight size={16} />
          <div className="mission"><span>02</span><div><b>盘中监测</b><small>量价异动 / 风险审查</small></div></div>
          <ChevronRight size={16} />
          <div className="mission"><span>03</span><div><b>盘后复核</b><small>信号归因 / 档案留存</small></div></div>
        </section>

        <div className="workspace-grid">
          <section className="primary-workspace">
            <div className="section-title">
              <div><p className="eyebrow">快速查询</p><h2>选择一只 A 股</h2></div>
            </div>
            <form className="symbol-search" onSubmit={submit}>
              <Search size={18} />
              <label className="visually-hidden" htmlFor="symbol">A 股代码</label>
              <input id="symbol" inputMode="numeric" maxLength={6} pattern="\d{6}" value={symbol} onChange={(event) => setSymbol(event.target.value.replace(/\D/g, ""))} />
              <span className="input-hint">输入六位 A 股代码</span>
              <button disabled={state.kind === "loading"} type="submit"><Radar size={16} />调取行情</button>
            </form>
            {state.kind === "idle" && <section className="empty-state"><Radar size={34} /><b>等待选择股票</b><p>输入 A 股代码后，系统会检查公开行情并给出观察结论。</p></section>}
            {state.kind === "loading" && <section className="loading-state" aria-busy="true"><span className="scanner" /><Activity size={20} />正在读取行情...</section>}
            {state.kind === "error" && <section className="error-state" role="alert"><ShieldAlert size={20} /><div><b>数据链路中断</b><p>{state.message}</p></div></section>}
            {state.kind === "ready" && <ResearchPanel card={state.card} />}
          </section>

          <aside className="right-rail">
            <section className="rail-section">
              <div className="rail-heading">
                <span>历史数据仓</span>
                <button className="rail-action" type="button" aria-label="同步历史日线" disabled={!syncHistory || dataState.kind === "syncing"} onClick={() => void syncDailyBars()}>
                  <RefreshCw size={14} />
                </button>
              </div>
              <DataStatusPanel state={dataState} />
            </section>
            <section className="rail-section">
              <div className="rail-heading"><span>处理进度</span><Archive size={15} /></div>
              <div className="event-line"><span className="event-node ready" /><div><b>行情</b><p>公开数据源待命</p></div><small>就绪</small></div>
              <div className="event-line"><span className="event-node" /><div><b>分析</b><p>等待选择股票</p></div><small>等待</small></div>
              <div className="event-line"><span className="event-node" /><div><b>风险</b><p>风险规则已加载</p></div><small>就绪</small></div>
            </section>
            <section className="rail-section protocol">
              <div className="rail-heading"><span>安全协议</span><ShieldCheck size={15} /></div>
              <ul><li>免费行情源可替换</li><li>超过三分钟自动拦截</li><li>所有快照进入审计库</li><li>不连接真实券商</li></ul>
            </section>
          </aside>
        </div>
      </main>}
    </div>
  );
}
