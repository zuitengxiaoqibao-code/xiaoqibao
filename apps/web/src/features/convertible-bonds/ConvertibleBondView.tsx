import { useEffect, useState } from "react";
import { AlertTriangle, FileText, Gauge, LoaderCircle, Search, ShieldAlert } from "lucide-react";
import type { BondCandidates, BondDashboard, BondDiagnosis } from "./types";

type Props = {
  loadDashboard: () => Promise<BondDashboard>;
  loadDiagnosis: (code: string) => Promise<BondDiagnosis>;
  loadCandidates: (filters?: Record<string, string>) => Promise<BondCandidates>;
  openBondCompliance?: () => void;
};

const sourceName: Record<string, string> = { tencent: "腾讯", eastmoney: "东方财富" };
const filterName: Record<string, string> = {
  max_conversion_premium: "最高转股溢价率",
  min_turnover_amount: "最低成交额（元）",
  min_remaining_size: "最低剩余规模（亿元）",
  min_days_to_maturity: "最低到期天数",
};
const value = (item: string | null, suffix = "") => item == null ? "未知" : `${item}${suffix}`;
const redemptionLabel: Record<string, string> = { unknown: "强赎状态未知", triggered: "强赎已触发", announced: "强赎已公告", completed: "强赎已完成" };

export function ConvertibleBondView({ loadDashboard, loadDiagnosis, loadCandidates, openBondCompliance }: Props) {
  const [tab, setTab] = useState<"overview" | "diagnosis" | "candidates">("overview");
  const [code, setCode] = useState("113065");
  const [dashboard, setDashboard] = useState<BondDashboard | null>(null);
  const [diagnosis, setDiagnosis] = useState<BondDiagnosis | null>(null);
  const [candidates, setCandidates] = useState<BondCandidates | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState({ max_conversion_premium: "", min_turnover_amount: "", min_remaining_size: "", min_days_to_maturity: "" });

  useEffect(() => { loadDashboard().then(setDashboard).catch((e) => setError(e.message)); }, [loadDashboard]);
  async function inspect() { setLoading(true); setError(""); try { setDiagnosis(await loadDiagnosis(code)); } catch (e) { setError(e instanceof Error ? e.message : "诊断失败"); } finally { setLoading(false); } }
  async function showCandidates() { setTab("candidates"); setLoading(true); setError(""); try { setCandidates(await loadCandidates(filters)); } catch (e) { setError(e instanceof Error ? e.message : "候选池加载失败"); } finally { setLoading(false); } }

  return <main className="bond-domain">
    <header className="bond-header"><div><p className="eyebrow">独立资产域 / CONVERTIBLE BONDS</p><h1>可转债专区</h1><p>行情、条款与正股上下文分层核验</p></div><div className="bond-domain-mark"><Gauge size={18} /><span>CB</span></div></header>
    <div className="bond-tabs" role="tablist">
      <button role="tab" aria-selected={tab === "overview"} onClick={() => setTab("overview")}>总览</button>
      <button role="tab" aria-selected={tab === "diagnosis"} onClick={() => setTab("diagnosis")}>诊断</button>
      <button role="tab" aria-selected={tab === "candidates"} onClick={() => void showCandidates()}>候选池</button>
    </div>
    {error && <div className="bond-alert" role="alert"><ShieldAlert size={18} />{error.includes("条款") ? `条款数据为空：${error}` : error}{error.includes("授权") && openBondCompliance && <button onClick={openBondCompliance}>检查数据授权</button>}</div>}
    {loading && <div className="bond-loading" aria-busy="true"><LoaderCircle size={18} />正在核验数据源...</div>}
    {tab === "overview" && !loading && <section className="bond-overview"><div><span>已存档转债</span><strong>{dashboard?.bond_count ?? "—"}</strong></div><div><span>条款状态</span><strong>{dashboard?.status === "empty" ? "暂无条款快照" : "快照可用"}</strong></div><p>这里仅汇总转债仓储，不读取 A 股候选排名。</p></section>}
    {tab === "diagnosis" && <section className="bond-diagnosis">
      <div className="bond-search"><Search size={17} /><label className="visually-hidden" htmlFor="bond-code">转债代码</label><input id="bond-code" value={code} maxLength={6} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}/><button onClick={() => void inspect()} disabled={loading}>诊断转债</button></div>
      {diagnosis && <>
        <div className="bond-state-line">{diagnosis.status === "stale_quote" && <span className="warning"><AlertTriangle size={15}/>行情已过期</span>}{diagnosis.status === "source_conflict" && <span className="danger"><AlertTriangle size={15}/>数据源冲突</span>}<span>{sourceName[diagnosis.quote.source] ?? diagnosis.quote.source} · {new Date(diagnosis.quote.observed_at).toLocaleString("zh-CN")}</span></div>
        <div className="bond-identity"><div><small>{diagnosis.bond.code}</small><h2>{diagnosis.bond.name}</h2></div><div><small>关联正股（独立上下文）</small><b>{diagnosis.linked_stock.code} · {diagnosis.linked_stock.name}</b><span>{diagnosis.linked_stock.price}</span></div></div>
        <div className="bond-metrics"><div><span>转股价值</span><b>{value(diagnosis.metrics.conversion_value)}</b></div><div><span>转股溢价率</span><b>{value(diagnosis.metrics.conversion_premium)}</b></div><div><span>剩余规模</span><b>{diagnosis.clause_snapshot.remaining_size}</b></div><div><span>到期日</span><b>{diagnosis.clause_snapshot.maturity}</b></div><div><span>纯债溢价</span><b>{diagnosis.metrics.pure_bond_premium == null ? "未知（缺少纯债价值）" : diagnosis.metrics.pure_bond_premium}</b></div><div><span>流动性</span><b>未知（缺少成交额）</b></div></div>
        <section className="clause-evidence"><header><FileText size={17}/><div><b>{redemptionLabel[diagnosis.strong_redemption.state] ?? "强赎状态未知"}</b><small>{sourceName[diagnosis.strong_redemption.source] ?? diagnosis.strong_redemption.source} · {new Date(diagnosis.strong_redemption.observed_at).toLocaleString("zh-CN")}</small></div></header>{diagnosis.strong_redemption.clause_text && <p>{diagnosis.strong_redemption.clause_text}</p>}<dl>{Object.entries(diagnosis.strong_redemption.evidence_fields ?? {}).map(([field, fieldValue]) => <div key={field}><dt>{field}</dt><dd>{fieldValue}</dd></div>)}</dl></section>
      </>}
    </section>}
    {tab === "candidates" && !loading && <section className="bond-candidates"><div className="candidate-filters">{Object.entries(filters).map(([key, current]) => <label key={key}><span>{filterName[key]}</span><input aria-label={filterName[key]} inputMode="decimal" value={current} onChange={(event) => setFilters((items) => ({ ...items, [key]: event.target.value }))} /></label>)}<button onClick={() => void showCandidates()}>应用筛选</button></div>{candidates?.items.length ? candidates.items.map((item) => <div key={item.bond_code}><b>{item.bond_code}</b><span>转股溢价 {value(item.conversion_premium)}</span><small>{item.risk.outcome}</small></div>) : <p>暂无符合条件的转债诊断快照</p>}</section>}
  </main>;
}
