import { AlertTriangle, RefreshCw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { RiskStatus } from "../governance/GovernanceViews";

export function BeginnerRiskView({ load }: { load?: () => Promise<RiskStatus> }) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState("");
  const request = useRef(0);
  const reload = useCallback(async () => {
    const current = ++request.current;
    if (!load) { setState("error"); setMessage("风险数据服务尚未连接"); return; }
    setState("loading"); setMessage("");
    try { await load(); if (current === request.current) setState("ready"); }
    catch (error) { if (current === request.current) { setState("error"); setMessage(error instanceof Error ? error.message : "风险数据暂不可用"); } }
  }, [load]);
  useEffect(() => { void reload(); return () => { request.current += 1; }; }, [reload]);
  return <main className="beginner-page beginner-risk"><header><p className="eyebrow">风险提醒</p><h1>当前风险状态</h1><p>这里汇总研究过程中需要优先留意的数据与市场风险。</p></header>
    {state === "loading" && <section className="beginner-empty" aria-busy="true"><RefreshCw className="spin" /><h2>正在检查风险状态</h2></section>}
    {state === "error" && <section className="beginner-empty risk-error" role="alert"><AlertTriangle /><h2>{message}</h2><button type="button" onClick={() => void reload()}>重试</button></section>}
    {state === "ready" && <section className="beginner-empty"><ShieldCheck /><h2>风险检查正常运行</h2><p>个股风险会随当前股票显示在行动卡中。出现明确风险时，系统会给出“回避”或“暂不参与”。</p></section>}
  </main>;
}
