import { useEffect, useMemo, useRef, useState } from "react";
import { Bookmark, BookmarkCheck, LoaderCircle, Search, ShieldAlert } from "lucide-react";

import type { CandidateBoard, CandidateEntry } from "../a-shares/types";
import { useSelectedInstrument } from "../instrument-selection/SelectedInstrumentProvider";
import type { AShareInstrument, InstrumentSearchResponse } from "./types";

const WATCHLIST_KEY = "qibao.a_share.watchlist.v1";

type Props = {
  loadCandidates: () => Promise<CandidateBoard>;
  search: (query: string) => Promise<InstrumentSearchResponse>;
};

function readWatchlist(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(WATCHLIST_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && /^\d{6}$/.test(item)) : [];
  } catch {
    return [];
  }
}

function mainFactor(entry: CandidateEntry): string {
  const factor = Object.entries(entry.score_breakdown).sort((left, right) => Number(right[1]) - Number(left[1]))[0];
  const names: Record<string, string> = { momentum: "动量", volume: "量能", trend: "趋势", liquidity: "流动性", risk_penalty: "风险扣分" };
  return factor ? `${names[factor[0]] ?? factor[0]} ${Number(factor[1]).toFixed(1)}` : "暂无因子归因";
}

function CandidateButton({ entry, selected, watched, onSelect, onWatch }: { entry: CandidateEntry; selected: boolean; watched: boolean; onSelect: () => void; onWatch: () => void }) {
  return <article className={selected ? "stock-option selected" : "stock-option"}>
    <button type="button" aria-pressed={selected} onClick={onSelect}>
      <span><b>{entry.symbol}</b><small>{entry.horizon === "short_term" ? "短线" : "波段"}</small></span>
      <span><strong>{Number(entry.score).toFixed(1)}</strong><small>候选分</small></span>
      <span className={Number(entry.factor_snapshot.return_5d) >= 0 ? "positive" : "negative"}>{(Number(entry.factor_snapshot.return_5d) * 100).toFixed(2)}%</span>
      <span><small>{mainFactor(entry)}</small><time>{entry.factor_snapshot.as_of}</time></span>
    </button>
    <button className="watch-button" type="button" aria-label={watched ? "移除自选" : "加入自选"} title={`${entry.symbol} ${watched ? "移除自选" : "加入自选"}`} onClick={onWatch}>{watched ? <BookmarkCheck size={15} /> : <Bookmark size={15} />}</button>
  </article>;
}

export function StockSelector({ loadCandidates, search }: Props) {
  const selection = useSelectedInstrument();
  const [board, setBoard] = useState<CandidateBoard | null>(null);
  const [candidateState, setCandidateState] = useState<"loading" | "ready" | "error">("loading");
  const [tab, setTab] = useState<"short_term" | "swing" | "watchlist">("short_term");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AShareInstrument[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState("");
  const [watchlist, setWatchlist] = useState(readWatchlist);
  const searchRequest = useRef(0);
  const initializedSelection = useRef(false);

  useEffect(() => {
    let active = true;
    setCandidateState("loading");
    void loadCandidates().then((value) => { if (active) { setBoard(value); setCandidateState("ready"); } }).catch((reason) => { if (active) { setError(reason instanceof Error ? reason.message : "候选池加载失败"); setCandidateState("error"); } });
    return () => { active = false; };
  }, [loadCandidates]);

  useEffect(() => {
    if (!board || initializedSelection.current) return;
    initializedSelection.current = true;
    if (selection.symbol) return;
    const firstCandidate = board.short_term[0] ?? board.swing[0];
    if (firstCandidate) selection.select(firstCandidate.symbol, "candidate");
  }, [board, selection]);

  useEffect(() => {
    const normalized = query.trim();
    if (!normalized) { searchRequest.current += 1; setResults([]); setSearchState("idle"); return; }
    const request = ++searchRequest.current;
    setSearchState("loading");
    const timer = window.setTimeout(() => void search(normalized).then((response) => {
      if (request === searchRequest.current) { setResults(response.items); setSearchState("ready"); }
    }).catch((reason) => {
      if (request === searchRequest.current) { setError(reason instanceof Error ? reason.message : "搜索失败"); setSearchState("error"); }
    }), /^\d{6}$/.test(normalized) ? 0 : 250);
    return () => window.clearTimeout(timer);
  }, [query, search]);

  const entries = useMemo(() => {
    if (!board) return [];
    if (tab === "watchlist") return [...board.short_term, ...board.swing].filter((entry, index, all) => watchlist.includes(entry.symbol) && all.findIndex((item) => item.symbol === entry.symbol) === index);
    return board[tab];
  }, [board, tab, watchlist]);

  function toggleWatch(symbol: string) {
    setWatchlist((current) => {
      const next = current.includes(symbol) ? current.filter((item) => item !== symbol) : [...current, symbol];
      localStorage.setItem(WATCHLIST_KEY, JSON.stringify(next));
      return next;
    });
  }

  return <section className="stock-selector" aria-label="A 股选择器">
    <header><div><p className="eyebrow">A SHARE / SELECTOR</p><h2>选择观察股票</h2></div><span>{selection.symbol ?? "尚未选择 A 股"}</span></header>
    <label className="stock-search"><Search size={16} /><span className="visually-hidden">搜索 A 股</span><input role="searchbox" aria-label="搜索 A 股" placeholder="输入六位代码或中文名称" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
    {searchState === "loading" && <p className="selector-message" role="status"><LoaderCircle size={15} />正在搜索...</p>}
    {query.trim() && searchState === "ready" && <div className="stock-search-results" role="listbox" aria-label="A 股搜索结果">{results.length ? results.map((item) => <button key={item.symbol} role="option" aria-selected={selection.symbol === item.symbol} type="button" onClick={() => { selection.select(item.symbol, "search"); setQuery(""); }}><b>{item.symbol}</b><span>{item.name}</span><small>{item.exchange.toUpperCase()} · {item.quote_quality}</small></button>) : <p>没有找到已验证的 A 股</p>}</div>}
    <div className="selector-tabs" role="tablist" aria-label="A 股候选分类">{([ ["short_term", "短线候选"], ["swing", "波段候选"], ["watchlist", "自选股"] ] as const).map(([key, name]) => <button key={key} role="tab" aria-selected={tab === key} type="button" onClick={() => setTab(key)}>{name}</button>)}</div>
    <div role="tabpanel" className="stock-options">
      {candidateState === "loading" && <p className="selector-message"><LoaderCircle size={15} />正在读取候选池...</p>}
      {candidateState === "error" && <p className="selector-message error" role="alert"><ShieldAlert size={15} />{error}</p>}
      {candidateState === "ready" && entries.length === 0 && <div className="selector-empty"><b>{board?.universe_status === "empty" ? "本地候选池为空" : tab === "watchlist" ? "暂无自选股数据" : "当前分类暂无候选"}</b><p>{board?.universe_status === "empty" ? "同步足够历史数据后才会生成候选，不会自动猜测股票。" : "可通过代码或名称搜索选择 A 股。"}</p></div>}
      {entries.map((entry) => <CandidateButton key={`${entry.horizon}-${entry.symbol}`} entry={entry} selected={selection.symbol === entry.symbol} watched={watchlist.includes(entry.symbol)} onSelect={() => selection.select(entry.symbol, "candidate")} onWatch={() => toggleWatch(entry.symbol)} />)}
    </div>
  </section>;
}
