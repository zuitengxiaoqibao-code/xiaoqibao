import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ExternalLink, ShieldAlert } from "lucide-react";
export type RiskStatus = { rule_version: string; limits: Record<string, string | number>; recent_rejections: Array<Record<string, string>> };
export type ComplianceStatus = { policy_state: string; sources: Array<Record<string, string | null>>; features: Array<{ feature: string; allowed: boolean; blocked_reasons: string[] }> };
export type AuditStatus = { state: string; findings: Array<{ finding_id: string; finding_type: string; severity: string; owner_department: string; resolution_state: string; evidence: string[]; snapshots: Array<{ snapshot_id: string; evidence_link: string }> }> };
type Asset = "a_share" | "convertible_bond";
type Props = { view: "xingbu" | "libu" | "dongchang"; initialAsset?: Asset; loadRisk?: () => Promise<RiskStatus>; loadCompliance?: (asset?: Asset) => Promise<ComplianceStatus>; loadAudit?: () => Promise<AuditStatus>; complianceAction?: (source: string, action: "authorize" | "revoke" | "acknowledge", permissionReference?: string, asset?: Asset) => Promise<unknown> };
type LoadedData =
  | { view: "xingbu"; data: RiskStatus }
  | { view: "libu"; asset: Asset; data: ComplianceStatus }
  | { view: "dongchang"; data: AuditStatus };
export function GovernanceView(props: Props) {
  const [loaded, setLoaded] = useState<LoadedData | null>(null); const [error, setError] = useState("");
  const [acting, setActing] = useState<string | null>(null);
  const [references, setReferences] = useState<Record<string, string>>({});
  const [asset, setAsset] = useState<Asset>(props.initialAsset ?? "a_share");
  const requestVersion = useRef(0);
  async function reload() {
    const request = ++requestVersion.current;
    const requestedView = props.view;
    const requestedAsset = asset;
    const loader = requestedView === "xingbu" ? props.loadRisk : requestedView === "libu" ? props.loadCompliance : props.loadAudit;
    if (!loader) { setError("服务未配置"); return; }
    setError("");
    try {
      const value = await (requestedView === "libu" && props.loadCompliance ? props.loadCompliance(requestedAsset) : loader());
      if (request !== requestVersion.current) return;
      if (requestedView === "xingbu") setLoaded({ view: requestedView, data: value as RiskStatus });
      else if (requestedView === "libu") setLoaded({ view: requestedView, asset: requestedAsset, data: value as ComplianceStatus });
      else setLoaded({ view: requestedView, data: value as AuditStatus });
    }
    catch (reason) {
      if (request === requestVersion.current) setError(reason instanceof Error ? reason.message : "服务不可用");
    }
  }
  useEffect(() => {
    setLoaded(null); setActing(null); void reload();
    return () => { requestVersion.current += 1; };
  }, [props.view, props.loadRisk, props.loadCompliance, props.loadAudit, asset]);
  const data = loaded?.view === props.view && (loaded.view !== "libu" || loaded.asset === asset) ? loaded.data : null;
  if (error && !data) return <main className="command-center"><section className="governance-page"><div className="error-state" role="alert"><AlertTriangle /><div><b>{error}</b><button type="button" onClick={() => void reload()}>重试</button></div></div></section></main>;
  if (!data) return <main className="command-center"><section className="governance-page">正在加载...</section></main>;
  async function runComplianceAction(source: string, action: "authorize" | "revoke" | "acknowledge") {
    if (!props.complianceAction || !props.loadCompliance) return;
    const request = ++requestVersion.current;
    const requestedAsset = asset;
    setActing(`${source}:${action}`); setError("");
    try {
      await props.complianceAction(source, action, references[source], requestedAsset);
      const value = await props.loadCompliance(requestedAsset);
      if (request === requestVersion.current) setLoaded({ view: "libu", asset: requestedAsset, data: value });
    }
    catch (reason) {
      if (request === requestVersion.current) setError(reason instanceof Error ? reason.message : "合规操作失败");
    }
    finally { if (request === requestVersion.current) setActing(null); }
  }
  if (props.view === "xingbu") { const risk = data as RiskStatus; return <main className="command-center"><section className="governance-page"><header><p className="eyebrow">刑部 / XINGBU</p><h1>实时风控</h1><span className="policy-badge">规则 {risk.rule_version}</span></header><div className="governance-grid">{Object.entries(risk.limits).map(([key, value]) => <div className="governance-unit" key={key}><small>{key}</small><b>{value}</b></div>)}</div><h2>近期拒绝</h2>{risk.recent_rejections.length === 0 ? <p className="no-audit">暂无拒绝记录</p> : risk.recent_rejections.map((item) => <article className="finding-row" key={item.decision_id}><ShieldAlert /><div><b>{item.symbol} / {item.reason_code}</b><small>{item.rule_version} · {item.order_id}</small></div></article>)}</section></main>; }
  if (props.view === "libu") { const policy = data as ComplianceStatus; return <main className="command-center"><section className="governance-page"><header><p className="eyebrow">礼部 / LIBU</p><h1>来源权限与声明</h1><div className="bond-tabs"><button onClick={() => setAsset("a_share")} aria-pressed={asset === "a_share"}>A 股</button><button onClick={() => setAsset("convertible_bond")} aria-pressed={asset === "convertible_bond"}>可转债</button></div>{policy.policy_state === "stale" && <span className="policy-badge warning">政策需复核</span>}</header>{error && <div className="governance-error" role="alert"><span>{error}</span><button type="button" onClick={() => void reload()}>重试</button></div>}{policy.sources.map((source) => { const name = String(source.source); return <article className="permission-row" key={name}><div><b>{name}</b><small>{source.permission_state} · 声明 {source.disclaimer_version} · {source.user_acknowledged_at ? "已确认" : "未确认"}</small><input aria-label={`${name} 权限依据`} value={references[name] ?? ""} onChange={(event) => setReferences((current) => ({ ...current, [name]: event.target.value }))} /></div><div className="action-row"><button disabled={acting !== null || !(references[name] ?? "").trim()} onClick={() => void runComplianceAction(name, "authorize")}>{acting === `${name}:authorize` ? "处理中..." : "授权"}</button><button disabled={acting !== null} onClick={() => void runComplianceAction(name, "acknowledge")}>{acting === `${name}:acknowledge` ? "处理中..." : "确认声明"}</button><button disabled={acting !== null} className="danger-action" onClick={() => void runComplianceAction(name, "revoke")}>{acting === `${name}:revoke` ? "处理中..." : "撤销授权"}</button></div></article>})}{policy.features.map((feature) => <div className={`feature-state ${feature.allowed ? "allowed" : "blocked"}`} key={feature.feature}>{feature.allowed ? <CheckCircle2 /> : <ShieldAlert />}<div><b>{feature.feature}</b><small>{feature.allowed ? "可用" : feature.blocked_reasons.join(", ")}</small></div></div>)}</section></main>; }
  const audit = data as AuditStatus; return <main className="command-center"><section className="governance-page"><header><p className="eyebrow">东厂 / DONGCHANG</p><h1>独立审计发现</h1></header>{audit.findings.length === 0 ? <p className="no-audit">暂无审计发现</p> : audit.findings.map((finding) => <article className={`audit-finding ${finding.severity}`} key={finding.finding_id}><div className="finding-heading"><b>{finding.finding_type}</b><span>{finding.severity.toUpperCase()}</span></div><p>责任部门：{finding.owner_department} · {finding.resolution_state}</p>{finding.snapshots.map((snapshot) => <div className="snapshot-link" key={snapshot.snapshot_id}><ExternalLink size={14} /><span>{snapshot.evidence_link}</span></div>)}</article>)}</section></main>;
}
