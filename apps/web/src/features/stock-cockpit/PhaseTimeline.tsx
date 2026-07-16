import { Activity, Clock3 } from "lucide-react";

import type { Advice, DecisionPhase } from "../decision-workbench/types";
import type { StockCockpitSnapshot } from "./types";

const phases: Array<[DecisionPhase, string, string]> = [
  ["premarket", "盘前研判", "开盘前的初始判断"],
  ["intraday", "盘中变化", "行情变化后的版本轨迹"],
  ["postclose", "盘后验证", "收盘后的验证与归因"],
];
const actions: Record<Advice["action"], string> = { observe: "观察", wait: "等待", avoid: "回避", invalidated: "已失效" };

export function PhaseTimeline({ phases: histories, symbol }: { phases: StockCockpitSnapshot["phases"]; symbol: string }) {
  return <section className="stock-phase-timeline" aria-labelledby="phase-timeline-title"><header className="cockpit-block-title"><div><p className="eyebrow">中书省 / 单股变化谱系</p><h2 id="phase-timeline-title">三阶段判断记录</h2></div><span>{symbol}</span></header>
    <div className="phase-lanes">{phases.map(([phase, title, description]) => {
      const history = histories[phase];
      const selected = (history?.advice ?? []).filter((item) => item.symbol === symbol);
      const versions = history?.change_stream ?? [];
      return <section className="phase-lane" key={phase}><header><div><Activity size={15} /><h3>{title}</h3></div><p>{description}</p></header>
        {selected.length === 0 ? <p className="phase-empty">该股票暂无已验证记录</p> : <div className="phase-records">{selected.map((item) => {
          const version = versions.find((candidate) => candidate.snapshot_id === item.snapshot_id);
          return <article key={item.advice_id}><div className="phase-record-time"><Clock3 size={13} /><time>{new Date(item.created_at).toLocaleTimeString("zh-CN", { hour12: false })}</time><span>{version ? `版本 #${version.sequence}` : "版本未标注"}</span></div>
            <div className="phase-record-body"><header><b>{actions[item.action]}</b><span>{item.horizon === "intraday" ? "短期" : "波段"}</span></header><h4>{item.conclusion}</h4>
              <p>变更字段：{item.changed_fields?.length ? item.changed_fields.join("、") : "首次记录或未标注"}</p><p>前序建议：{item.previous_advice_id ?? "无"}</p>
              {item.supporting_evidence.map((evidence) => <p className="phase-trigger" key={evidence.evidence_id}>触发证据：{evidence.summary}<small>{evidence.source} · {new Date(evidence.observed_at).toLocaleString("zh-CN", { hour12: false })}</small></p>)}
              {item.plain_language_explanation && <p>通俗解释：{item.plain_language_explanation}</p>}
              {phase === "postclose" && <p>盘后归因：后端当前未提供独立归因字段</p>}
            </div></article>;
        })}</div>}
      </section>;
    })}</div>
  </section>;
}
