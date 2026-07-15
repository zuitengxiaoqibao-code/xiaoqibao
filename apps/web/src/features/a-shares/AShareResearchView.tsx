import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, AlertTriangle, BarChart3, ChevronRight, Database,
  LineChart, LoaderCircle, RefreshCw, ShieldAlert, Target, TrendingUp,
} from "lucide-react";

import type { AShareDiagnosis, CandidateBoard, CandidateEntry, DiagnosisSection } from "./types";
import { useOptionalSelectedInstrument } from "../instrument-selection/SelectedInstrumentProvider";


type Props = {
  loadCandidates: () => Promise<CandidateBoard>;
  loadDiagnosis: (symbol: string, asOf?: string) => Promise<AShareDiagnosis>;
};

const sectionOrder = ["market", "price_volume", "trend", "valuation", "fundamentals", "events", "industry", "risk"];
const sectionNames: Record<string, string> = {
  market: "实时行情", price_volume: "量价结构", trend: "趋势结构", valuation: "估值",
  fundamentals: "基本面", events: "关联事件", industry: "行业归属", risk: "风险结论",
};
const metricNames: Record<string, string> = {
  name: "股票名称", price: "最新价", change_percent: "涨跌幅", turnover_rate: "换手率",
  close: "收盘价", return_5d: "近 5 日变化", average_amount_20d: "20 日平均成交额",
  volume_ratio: "当日量比", distance_ma20: "MA20 趋势偏离", return_20d: "近 20 日变化",
  volatility_20d: "20 日波动", drawdown_60d: "60 日回撤", pe_ttm: "市盈率 TTM",
  pb: "市净率", market_cap_yi: "总市值（亿元）", report_period: "财报期",
  industry: "财务行业", eps: "每股收益", roe: "净资产收益率", net_profit: "净利润",
  revenue: "主营收入", book_value_per_share: "每股净资产", total_shares: "总股本",
  event_count: "关联事件数", industries: "行业标签", missing_section_count: "缺失分区数",
  symbol: "股票代码",
  momentum: "动量贡献", volume: "量能贡献", trend: "趋势贡献",
  liquidity: "流动性贡献", risk_penalty: "波动风险扣分",
  volatility_penalty: "波动扣分", drawdown_penalty: "回撤扣分",
};
const sourceNames: Record<string, string> = {
  tencent: "腾讯行情", mootdx: "通达信日线", "mootdx-finance": "通达信财务",
  "frozen-news-events": "冻结新闻事件", "qibao-risk-v1": "刑部规则 v1",
  "local-daily-bars": "本地日线仓",
};
const percentMetrics = new Set(["change_percent", "turnover_rate", "return_5d", "distance_ma20", "return_20d", "volatility_20d", "drawdown_60d", "roe"]);

function displayMetric(key: string, value: string | number | null): string {
  if (value === null || value === "") return "暂无数据";
  if (!percentMetrics.has(key)) return String(value);
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (key === "change_percent" || key === "turnover_rate" || key === "roe") return `${number.toFixed(2)}%`;
  return `${(number * 100).toFixed(2)}%`;
}

function observedAt(value: string | null): string {
  if (!value) return "时间未提供";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN", { hour12: false });
}

function CandidateRow({ entry, selected, onSelect }: { entry: CandidateEntry; selected: boolean; onSelect: () => void }) {
  const positive = Number(entry.factor_snapshot.return_5d) >= 0;
  return (
    <article className={selected ? "a-candidate selected" : "a-candidate"}>
      <button type="button" onClick={onSelect} aria-pressed={selected}>
        <span><b>{entry.symbol}</b><small>{entry.horizon === "short_term" ? "SHORT" : "SWING"}</small></span>
        <span className={positive ? "candidate-move positive" : "candidate-move negative"}>{(Number(entry.factor_snapshot.return_5d) * 100).toFixed(2)}%</span>
        <strong>{Number(entry.score).toFixed(1)}</strong><ChevronRight size={15} />
      </button>
      <details>
        <summary>因子贡献</summary>
        <dl>{Object.entries(entry.score_breakdown).map(([key, value]) => <div key={key}><dt>{metricNames[key] ?? key}</dt><dd>{Number(value).toFixed(1)}</dd></div>)}</dl>
      </details>
    </article>
  );
}

function Section({ name, section }: { name: string; section: DiagnosisSection }) {
  const unavailable = section.status === "unavailable";
  return (
    <section className={unavailable ? "diagnosis-section unavailable" : "diagnosis-section"}>
      <header>
        <div><span>{sectionNames[name] ?? name}</span><small>{sourceNames[section.source] ?? section.source}</small></div>
        <b>{unavailable ? "UNAVAILABLE" : "VERIFIED"}</b>
      </header>
      {unavailable ? (
        <div className="section-unavailable"><AlertTriangle size={16} /><div><strong>{sectionNames[name] ?? name}数据暂不可用</strong><p>{section.explanation}</p></div></div>
      ) : (
        <>
          <dl className="diagnosis-metrics">{Object.entries(section.metrics).map(([key, value]) => <div key={key}><dt>{metricNames[key] ?? key}</dt><dd>{displayMetric(key, value)}</dd></div>)}</dl>
          <p className="section-explanation">{section.explanation}</p>
        </>
      )}
      <footer><span>数据截至 {observedAt(section.observed_at)}</span>{section.evidence_ids.length > 0 && <code>{section.evidence_ids.length} 条冻结证据</code>}</footer>
    </section>
  );
}

export function AShareResearchView({ loadCandidates, loadDiagnosis }: Props) {
  const globalSelection = useOptionalSelectedInstrument();
  const [board, setBoard] = useState<CandidateBoard | null>(null);
  const [tab, setTab] = useState<"short_term" | "swing">("short_term");
  const [selected, setSelected] = useState<string | null>(null);
  const [diagnosis, setDiagnosis] = useState<AShareDiagnosis | null>(null);
  const [boardState, setBoardState] = useState<"loading" | "ready" | "error">("loading");
  const [diagnosisState, setDiagnosisState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState("");
  const diagnosisRequest = useRef(0);
  const shortTabRef = useRef<HTMLButtonElement>(null);
  const swingTabRef = useRef<HTMLButtonElement>(null);

  function resetDiagnosis() {
    diagnosisRequest.current += 1;
    setSelected(null); setDiagnosis(null); setDiagnosisState("idle");
  }

  function refresh() {
    setBoardState("loading"); setError(""); resetDiagnosis();
    void loadCandidates().then((value) => { setBoard(value); setBoardState("ready"); }).catch((reason) => { setError(reason instanceof Error ? reason.message : "候选池加载失败"); setBoardState("error"); });
  }
  useEffect(refresh, [loadCandidates]);
  const entries = useMemo(() => board ? board[tab] : [], [board, tab]);

  function loadSelectedDiagnosis(symbol: string) {
    if (!board) return;
    const request = ++diagnosisRequest.current;
    setSelected(symbol); setDiagnosisState("loading"); setError("");
    void loadDiagnosis(symbol, board.as_of).then((value) => {
      if (request !== diagnosisRequest.current) return;
      setDiagnosis(value); setDiagnosisState("ready");
    }).catch((reason) => {
      if (request !== diagnosisRequest.current) return;
      setDiagnosis(null); setError(reason instanceof Error ? reason.message : "诊断加载失败"); setDiagnosisState("error");
    });
  }

  function inspect(symbol: string) {
    if (globalSelection && globalSelection.symbol !== symbol) { globalSelection.select(symbol, "candidate"); return; }
    loadSelectedDiagnosis(symbol);
  }

  useEffect(() => {
    if (!board || !globalSelection?.symbol) return;
    if (selected === globalSelection.symbol && diagnosisState !== "idle") return;
    loadSelectedDiagnosis(globalSelection.symbol);
  }, [board, globalSelection?.symbol, diagnosisState, selected]);

  function selectTab(nextTab: "short_term" | "swing") {
    setTab(nextTab); resetDiagnosis(); setError("");
  }

  function handleTabKey(key: string) {
    if (key !== "ArrowLeft" && key !== "ArrowRight") return;
    const nextTab = tab === "short_term" ? "swing" : "short_term";
    selectTab(nextTab);
    (nextTab === "short_term" ? shortTabRef : swingTabRef).current?.focus();
  }

  return (
    <main className="a-share-domain">
      <header className="a-share-header">
        <div><p className="eyebrow">A SHARE / 中书省研究域</p><h1>A 股研究工作区</h1><p>本地候选生成 · 确定性评分 · 八分区证据诊断</p></div>
        <div className="research-freeze"><Target size={16} /><div><span>研究冻结日</span><b>{board?.as_of ?? "等待候选池"}</b></div></div>
      </header>
      {boardState === "error" && <div className="a-share-error" role="alert"><ShieldAlert size={17} /><span>{error}</span><button type="button" onClick={refresh}><RefreshCw size={14} />重试</button></div>}
      <div className="a-share-layout">
        <section className="candidate-console">
          <header><div><p className="eyebrow">ZHONGSHU / RANKING</p><h2>候选观察榜</h2></div><span>{entries.length.toString().padStart(2, "0")} / {board ? board.short_term.length + board.swing.length : "--"}</span></header>
          <div className="candidate-tabs" role="tablist" aria-label="A 股候选周期">
            <button ref={shortTabRef} id="a-share-short-term-tab" role="tab" aria-controls="a-share-candidate-panel" aria-selected={tab === "short_term"} tabIndex={tab === "short_term" ? 0 : -1} onKeyDown={(event) => handleTabKey(event.key)} onClick={() => selectTab("short_term")}>短线榜</button>
            <button ref={swingTabRef} id="a-share-swing-tab" role="tab" aria-controls="a-share-candidate-panel" aria-selected={tab === "swing"} tabIndex={tab === "swing" ? 0 : -1} onKeyDown={(event) => handleTabKey(event.key)} onClick={() => selectTab("swing")}>波段榜</button>
          </div>
          <div id="a-share-candidate-panel" role="tabpanel" aria-labelledby={tab === "short_term" ? "a-share-short-term-tab" : "a-share-swing-tab"}>
            {boardState === "loading" && <div className="candidate-message"><LoaderCircle size={18} /><span>正在读取本地候选宇宙...</span></div>}
            {boardState === "ready" && entries.length === 0 && board?.universe_status === "empty" && <div className="candidate-message empty"><Database size={24} /><b>本地候选池为空</b><p>先到工部同步至少 60 根日线，再生成可重复候选榜。</p></div>}
            {boardState === "ready" && entries.length === 0 && board?.universe_status !== "empty" && <div className="candidate-message empty"><Database size={24} /><b>当前榜单暂无候选</b><p>本次确定性筛选没有标的进入该周期榜单。</p></div>}
            <div className="candidate-list">{entries.map((entry) => <CandidateRow key={entry.symbol} entry={entry} selected={selected === entry.symbol} onSelect={() => inspect(entry.symbol)} />)}</div>
            {board && board.exclusions.length > 0 && <div className="candidate-exclusions"><AlertTriangle size={14} /><span>{board.exclusions.length} 只股票因流动性或历史质量被排除</span></div>}
            {board?.snapshot_id && <footer className="snapshot-foot"><span>候选快照</span><code>{board.snapshot_id}</code></footer>}
          </div>
        </section>

        <section className="diagnosis-console">
          <header><div><p className="eyebrow">EVIDENCE DIAGNOSIS</p><h2>{diagnosis ? `${diagnosis.sections.market.metrics.name ?? diagnosis.symbol} · ${diagnosis.symbol}` : "单股证据诊断"}</h2></div>{diagnosis && <span className={diagnosis.overall_status === "ready" ? "diagnosis-status ready" : "diagnosis-status partial"}>{diagnosis.overall_status === "ready" ? "数据完整" : "部分降级"}</span>}</header>
          {diagnosisState === "idle" && <div className="diagnosis-wait"><BarChart3 size={34} /><b>选择候选标的</b><p>查看量价、趋势、估值、基本面、事件、行业和风险证据。</p></div>}
          {diagnosisState === "loading" && <div className="diagnosis-wait loading"><Activity size={22} /><b>正在冻结并核验诊断证据...</b></div>}
          {diagnosisState === "error" && <div className="a-share-error" role="alert"><ShieldAlert size={17} /><span>{error}</span></div>}
          {diagnosisState === "ready" && diagnosis && <>
            <div className="diagnosis-summary"><div><TrendingUp size={15} /><span>结论</span><b>{diagnosis.action === "observe" ? "仅观察" : "已拦截"}</b></div><div><LineChart size={15} /><span>因子版本</span><b>{diagnosis.factor_version}</b></div><div><AlertTriangle size={15} /><span>缺失分区</span><b>{diagnosis.missing_data.length}</b></div></div>
            <div className="diagnosis-sections">{sectionOrder.map((name) => diagnosis.sections[name] && <Section key={name} name={name} section={diagnosis.sections[name]} />)}</div>
            {diagnosis.snapshot_id && <footer className="snapshot-foot"><span>诊断快照</span><code>{diagnosis.snapshot_id}</code></footer>}
          </>}
        </section>
      </div>
    </main>
  );
}
