import {
  BellRing, BookOpenText, CandlestickChart, History, Newspaper, Settings2,
  ShieldAlert, Sparkles,
} from "lucide-react";

export type BeginnerView = "dashboard" | "a_shares" | "news" | "risk" | "history" | "settings" | "bonds";

const entries = [
  ["dashboard", "今日研判", Sparkles],
  ["a_shares", "A 股观察", CandlestickChart],
  ["news", "新闻热点", Newspaper],
  ["risk", "风险提醒", ShieldAlert],
  ["history", "历史复盘", History],
  ["settings", "数据设置", Settings2],
] as const;

export function BeginnerNavigation({ active, onNavigate }: {
  active: BeginnerView;
  onNavigate: (view: BeginnerView) => void;
}) {
  return <aside className="beginner-sidebar">
    <div className="beginner-brand"><span><BookOpenText size={20} /></span><div><strong>小七宝</strong><small>A 股观察台</small></div></div>
    <nav aria-label="主要功能">
      {entries.map(([view, label, Icon]) => <button className={active === view ? "active" : ""} type="button" key={view} aria-current={active === view ? "page" : undefined} onClick={() => onNavigate(view)}><Icon size={18} /><span>{label}</span></button>)}
    </nav>
    <div className="asset-separator"><span>独立资产</span></div>
    <button className={`bond-navigation ${active === "bonds" ? "active" : ""}`} type="button" aria-label="可转债" onClick={() => onNavigate("bonds")}><BellRing size={18} /><span><b>可转债</b><small>独立观察空间</small></span></button>
    <p className="beginner-disclaimer">只做观察与风险提示<br />不连接券商，不构成投资建议</p>
  </aside>;
}
