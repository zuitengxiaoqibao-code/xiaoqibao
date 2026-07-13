import { FormEvent, useState } from "react";
import {
  Activity, Archive, BookOpenCheck, Boxes, BriefcaseBusiness, Building2,
  ChevronRight, CircleDollarSign, Database, Gauge, Landmark, Radar, Search,
  RefreshCw, ShieldAlert, ShieldCheck, Siren, Workflow,
} from "lucide-react";

import { DataStatusPanel } from "../data-status/DataStatusPanel";
import type { DataStatusState, SyncReport } from "../data-status/types";
import { BacktestPanel } from "../backtest/BacktestPanel";
import type { BacktestResult } from "../backtest/types";
import { PaperTradingPanel } from "../paper-trading/PaperTradingPanel";
import type { OrderResult, PaperAccount, Portfolio } from "../paper-trading/types";
import type { ResearchCard } from "./types";

type ViewState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; card: ResearchCard }
  | { kind: "error"; message: string };

type Props = {
  loadSnapshot: (symbol: string) => Promise<ResearchCard>;
  syncHistory?: (symbol: string, limit?: number) => Promise<SyncReport>;
  runBacktest?: (symbol: string) => Promise<BacktestResult>;
  loadPaperPortfolio?: () => Promise<Portfolio>;
  createPaperAccount?: () => Promise<PaperAccount>;
  submitPaperOrder?: (symbol: string, side: "buy" | "sell", shares: number) => Promise<OrderResult>;
};

const departments = [
  { name: "今日工作台", detail: "全域态势", icon: Gauge, active: true },
  { name: "中书省", detail: "策略研究", icon: BookOpenCheck },
  { name: "吏部", detail: "资金中心", icon: CircleDollarSign },
  { name: "户部", detail: "交易中心", icon: BriefcaseBusiness },
  { name: "东厂", detail: "监察审核", icon: Radar },
  { name: "礼部", detail: "合规中心", icon: Landmark },
  { name: "兵部", detail: "操盘中心", icon: Siren },
  { name: "尚书省", detail: "指令执行", icon: Workflow },
  { name: "刑部", detail: "实时风控", icon: ShieldAlert },
  { name: "工部", detail: "数据运维", icon: Database },
];

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
          <div><b>刑部否决</b>{card.invalid_reasons.map((reason) => <p key={reason}>{reason}</p>)}</div>
        </div>
      )}
    </section>
  );
}

export function Dashboard({ loadSnapshot, syncHistory, runBacktest, loadPaperPortfolio, createPaperAccount, submitPaperOrder }: Props) {
  const [state, setState] = useState<ViewState>({ kind: "idle" });
  const [symbol, setSymbol] = useState("600000");
  const [dataState, setDataState] = useState<DataStatusState>({ kind: "idle" });

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
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-sigil"><Building2 size={18} /></div>
          <div><strong>小七宝</strong><span>量化决策台</span></div>
        </div>
        <div className="domain-switcher">
          <span className="domain-dot" />
          <div><b>A 股主域</b><small>ASHARE COMMAND</small></div>
          <ChevronRight size={15} />
        </div>
        <nav aria-label="部门导航">
          <p className="nav-label">中央机构</p>
          {departments.map(({ name, detail, icon: Icon, active }) => (
            <button className={active ? "nav-item active" : "nav-item"} key={name} type="button">
              <Icon size={16} strokeWidth={1.7} />
              <span><b>{name}</b><small>{detail}</small></span>
            </button>
          ))}
        </nav>
        <button className="bond-entry" type="button">
          <Boxes size={16} /><span><b>可转债专区</b><small>独立资产域</small></span><ChevronRight size={15} />
        </button>
        <div className="sidebar-foot"><span className="pulse-dot" />系统本地运行</div>
      </aside>

      <main className="command-center">
        <header className="topbar">
          <div><p className="eyebrow">尚书省 / 全域指令视图</p><h1>今日情报态势</h1></div>
          <div className="system-state"><span className="pulse-dot" /><div><b>工部数据链路</b><small>等待调取</small></div></div>
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
              <div><p className="eyebrow">工部数据查询</p><h2>A 股单标的侦测</h2></div>
              <span className="section-code">GB-DATA / 01</span>
            </div>
            <form className="symbol-search" onSubmit={submit}>
              <Search size={18} />
              <label className="visually-hidden" htmlFor="symbol">A 股代码</label>
              <input id="symbol" inputMode="numeric" maxLength={6} pattern="\d{6}" value={symbol} onChange={(event) => setSymbol(event.target.value.replace(/\D/g, ""))} />
              <span className="input-hint">输入六位 A 股代码</span>
              <button disabled={state.kind === "loading"} type="submit"><Radar size={16} />调取行情</button>
            </form>
            {state.kind === "idle" && <section className="empty-state"><Radar size={34} /><b>等待标的指令</b><p>输入 A 股代码后，工部将获取真实行情；中书省生成观察摘要，刑部复核数据时效。</p></section>}
            {state.kind === "loading" && <section className="loading-state" aria-busy="true"><span className="scanner" /><Activity size={20} />正在调取工部行情...</section>}
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
              <div className="rail-heading"><span>指令流</span><Archive size={15} /></div>
              <div className="event-line"><span className="event-node ready" /><div><b>工部</b><p>行情适配器待命</p></div><small>READY</small></div>
              <div className="event-line"><span className="event-node" /><div><b>中书省</b><p>等待研究输入</p></div><small>STANDBY</small></div>
              <div className="event-line"><span className="event-node" /><div><b>刑部</b><p>风险规则已装载</p></div><small>ARMED</small></div>
            </section>
            <section className="rail-section protocol">
              <div className="rail-heading"><span>安全协议</span><ShieldCheck size={15} /></div>
              <ul><li>免费行情源可替换</li><li>超过三分钟自动拦截</li><li>所有快照进入审计库</li><li>不连接真实券商</li></ul>
            </section>
          </aside>
        </div>
        {runBacktest && <BacktestPanel symbol={symbol} runBacktest={runBacktest} />}
        {loadPaperPortfolio && createPaperAccount && submitPaperOrder && (
          <PaperTradingPanel
            symbol={symbol}
            loadPortfolio={loadPaperPortfolio}
            createAccount={createPaperAccount}
            submitOrder={submitPaperOrder}
          />
        )}
      </main>
    </div>
  );
}
