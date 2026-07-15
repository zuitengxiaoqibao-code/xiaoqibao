import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bookmark, BookmarkCheck, LoaderCircle, RefreshCw, Search, ShieldAlert } from "lucide-react";

import type { CandidateBoard, CandidateEntry } from "../a-shares/types";
import { isAShareSymbol, useSelectedInstrument } from "../instrument-selection/SelectedInstrumentProvider";
import type { AShareInstrument, InstrumentSearchResponse } from "./types";

const WATCHLIST_KEY = "qibao.a_share.watchlist.v1";
type CandidateTab = "short_term" | "swing" | "watchlist";
type Props = { loadCandidates: () => Promise<CandidateBoard>; search: (query: string) => Promise<InstrumentSearchResponse>; pollIntervalMs?: number };

function readWatchlist(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(WATCHLIST_KEY) ?? "[]");
    const cleaned = Array.isArray(value) ? [...new Set(value.filter((item): item is string => typeof item === "string" && isAShareSymbol(item)))] : [];
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(cleaned));
    return cleaned;
  } catch { localStorage.setItem(WATCHLIST_KEY, "[]"); return []; }
}

function mainFactor(entry: CandidateEntry): string {
  const factor = Object.entries(entry.score_breakdown).sort((left, right) => Number(right[1]) - Number(left[1]))[0];
  const names: Record<string, string> = { momentum: "动量", volume: "量能", trend: "趋势", liquidity: "流动性", risk_penalty: "风险扣分" };
  return factor ? `${names[factor[0]] ?? factor[0]} ${Number(factor[1]).toFixed(1)}` : "暂无因子归因";
}

function WatchButton({ symbol, watched, onToggle }: { symbol: string; watched: boolean; onToggle: () => void }) {
  return <button className="watch-button" type="button" aria-label={`${watched ? "将" : "将"} ${symbol} ${watched ? "移出自选" : "加入自选"}`} title={`${symbol} ${watched ? "移出自选" : "加入自选"}`} onClick={onToggle}>{watched ? <BookmarkCheck size={15} /> : <Bookmark size={15} />}</button>;
}

function CandidateRow({ entry, identity, selected, watched, onSelect, onWatch }: { entry: CandidateEntry; identity?: AShareInstrument; selected: boolean; watched: boolean; onSelect: () => void; onWatch: () => void }) {
  const fiveDay = Number(entry.factor_snapshot.return_5d);
  return <article className={selected ? "stock-option selected" : "stock-option"}>
    <button type="button" aria-pressed={selected} onClick={onSelect}>
      <span><b>{entry.symbol}</b><small>{identity?.name ?? "名称数据不可用"} · {entry.horizon === "short_term" ? "短线" : "波段"}</small></span>
      <span><strong>{Number(entry.score).toFixed(1)}</strong><small>候选分</small></span>
      <span><small>最新价不可用</small><small>当前涨跌不可用</small></span>
      <span><small>{mainFactor(entry)} · 近 5 日 {fiveDay >= 0 ? "+" : ""}{(fiveDay * 100).toFixed(2)}%</small><time>{entry.factor_snapshot.as_of}</time></span>
    </button>
    <WatchButton symbol={entry.symbol} watched={watched} onToggle={onWatch} />
  </article>;
}

function WatchlistRow({ symbol, item, error, selected, onSelect, onWatch, onRetry }: { symbol: string; item?: AShareInstrument; error?: string; selected: boolean; onSelect: () => void; onWatch: () => void; onRetry: () => void }) {
  return <article className={selected ? "stock-option selected" : "stock-option"}>
    <button type="button" aria-pressed={selected} onClick={onSelect}><span><b>{symbol}</b><small>{item?.name ?? "身份数据暂不可用"}</small></span><span><small>最新价不可用</small><small>当前涨跌不可用</small></span><span>{error ? <small role="alert">{error}</small> : <small>{item ? `${item.exchange.toUpperCase()} · ${item.quote_quality}` : "正在恢复身份"}</small>}{item && <time>{new Date(item.observed_at).toLocaleString("zh-CN")}</time>}</span></button>
    {error && <button className="identity-retry" type="button" aria-label={`重试 ${symbol} 身份`} onClick={onRetry}><RefreshCw size={14} /></button>}
    <WatchButton symbol={symbol} watched onToggle={onWatch} />
  </article>;
}

export function StockSelector({ loadCandidates, search, pollIntervalMs = 30_000 }: Props) {
  const selection = useSelectedInstrument();
  const [board, setBoard] = useState<CandidateBoard | null>(null);
  const [candidateState, setCandidateState] = useState<"loading" | "ready" | "error">("loading");
  const [tab, setTab] = useState<CandidateTab>("short_term");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AShareInstrument[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [searchError, setSearchError] = useState("");
  const [candidateError, setCandidateError] = useState("");
  const [watchlist, setWatchlist] = useState(readWatchlist);
  const [identities, setIdentities] = useState<Record<string, AShareInstrument>>({});
  const [identityErrors, setIdentityErrors] = useState<Record<string, string>>({});
  const searchRequest = useRef(0);
  const candidateRequest = useRef(0);
  const mounted = useRef(true);
  const initializedSelection = useRef(false);
  const identityRequests = useRef(new Set<string>());
  const identityGeneration = useRef<Record<string, number>>({});
  const tabRefs = useRef<Record<CandidateTab, HTMLButtonElement | null>>({ short_term: null, swing: null, watchlist: null });

  const refreshCandidates = useCallback(async (initial = false) => {
    const request = ++candidateRequest.current;
    if (initial) setCandidateState("loading");
    try { const value = await loadCandidates(); if (mounted.current && request === candidateRequest.current) { setBoard(value); setCandidateState("ready"); setCandidateError(""); } }
    catch (reason) { if (mounted.current && request === candidateRequest.current) { setCandidateError(reason instanceof Error ? reason.message : "候选池加载失败"); setCandidateState("error"); } }
  }, [loadCandidates]);

  useEffect(() => { mounted.current = true; void refreshCandidates(true); const timer = window.setInterval(() => void refreshCandidates(), pollIntervalMs); return () => { mounted.current = false; candidateRequest.current += 1; window.clearInterval(timer); }; }, [pollIntervalMs, refreshCandidates]);
  useEffect(() => {
    if (!board || initializedSelection.current) return;
    initializedSelection.current = true;
    if (!selection.symbol) { const first = board.short_term[0] ?? board.swing[0]; if (first) selection.select(first.symbol, "candidate"); }
  }, [board, selection]);

  const resolveSymbols = useCallback(async (symbols: string[]) => {
    const unique = [...new Set(symbols)].filter((symbol) => !identityRequests.current.has(symbol));
    if (!unique.length) return;
    unique.forEach((symbol) => identityRequests.current.add(symbol));
    const settled = await Promise.all(unique.map(async (symbol) => {
      const generation = (identityGeneration.current[symbol] ?? 0) + 1;
      identityGeneration.current[symbol] = generation;
      try { const response = await search(symbol); const item = response.items.find((candidate) => candidate.symbol === symbol); if (!item) throw new Error("身份目录未返回该 A 股"); return { symbol, generation, item }; }
      catch (reason) { return { symbol, generation, error: reason instanceof Error ? reason.message : "身份查询失败" }; }
    }));
    if (!mounted.current) return;
    const currentResults = settled.filter((result) => identityGeneration.current[result.symbol] === result.generation);
    setIdentities((current) => Object.fromEntries([...Object.entries(current), ...currentResults.flatMap((result) => result.item ? [[result.symbol, result.item] as const] : [])]));
    setIdentityErrors((current) => {
      const next = { ...current };
      currentResults.forEach((result) => { if (result.error) next[result.symbol] = result.error; else delete next[result.symbol]; });
      return next;
    });
  }, [search]);

  useEffect(() => { if (board) void resolveSymbols([...board.short_term, ...board.swing].map((item) => item.symbol)); }, [board, resolveSymbols]);
  useEffect(() => { void resolveSymbols(watchlist); }, [watchlist, resolveSymbols]);

  const executeSearch = useCallback((value: string, request = ++searchRequest.current) => {
    setSearchState("loading"); setSearchError("");
    void search(value).then((response) => { if (request === searchRequest.current) { setResults(response.items); setSearchState("ready"); } }).catch((reason) => { if (request === searchRequest.current) { setSearchError(reason instanceof Error ? reason.message : "搜索失败"); setSearchState("error"); } });
  }, [search]);

  useEffect(() => {
    const request = ++searchRequest.current;
    const normalized = query.trim();
    if (!normalized) { setResults([]); setSearchState("idle"); return; }
    setSearchState("loading"); setSearchError("");
    const timer = window.setTimeout(() => executeSearch(normalized, request), /^\d{6}$/.test(normalized) ? 0 : 250);
    return () => window.clearTimeout(timer);
  }, [executeSearch, query]);

  const candidateEntries = useMemo(() => board && tab !== "watchlist" ? board[tab] : [], [board, tab]);
  function toggleWatch(symbol: string) { if (!isAShareSymbol(symbol)) return; setWatchlist((current) => { const next = current.includes(symbol) ? current.filter((item) => item !== symbol) : [...current, symbol]; localStorage.setItem(WATCHLIST_KEY, JSON.stringify(next)); return next; }); }
  function retryIdentity(symbol: string) { identityRequests.current.delete(symbol); setIdentityErrors((current) => { const next = { ...current }; delete next[symbol]; return next; }); void resolveSymbols([symbol]); }
  function selectTab(next: CandidateTab) { setTab(next); window.setTimeout(() => tabRefs.current[next]?.focus(), 0); }
  function onTabKey(event: React.KeyboardEvent<HTMLButtonElement>) { if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return; event.preventDefault(); const order: CandidateTab[] = ["short_term", "swing", "watchlist"]; const offset = event.key === "ArrowLeft" ? -1 : 1; selectTab(order[(order.indexOf(tab) + offset + order.length) % order.length]); }
  const tabs = [["short_term", "短线候选"], ["swing", "波段候选"], ["watchlist", "自选股"]] as const;

  return <section className="stock-selector" aria-label="A 股选择器">
    <header><div><p className="eyebrow">A SHARE / SELECTOR</p><h2>选择观察股票</h2></div><span>{selection.symbol ?? "尚未选择 A 股"}</span><button type="button" className="selector-refresh" aria-label="刷新候选" onClick={() => { void refreshCandidates(); watchlist.forEach(retryIdentity); }}><RefreshCw size={14} /></button></header>
    <label className="stock-search"><Search size={16} /><span className="visually-hidden">搜索 A 股</span><input role="searchbox" aria-label="搜索 A 股" placeholder="输入六位代码或中文名称" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
    {searchState === "loading" && <p className="selector-message" role="status"><LoaderCircle size={15} />正在搜索...</p>}
    {query.trim() && searchState === "error" && <div className="selector-message error" role="alert"><ShieldAlert size={15} /><span>{searchError}</span><button type="button" onClick={() => executeSearch(query.trim())}>重试搜索</button></div>}
    {query.trim() && searchState === "ready" && <div className="stock-search-results" role="listbox" aria-label="A 股搜索结果">{results.length ? results.map((item) => <article key={item.symbol}><button role="option" aria-selected={selection.symbol === item.symbol} type="button" onClick={() => { selection.select(item.symbol, "search"); setQuery(""); }}><b>{item.symbol}</b><span>{item.name}</span><small>{item.exchange.toUpperCase()} · {item.quote_quality}</small></button><WatchButton symbol={item.symbol} watched={watchlist.includes(item.symbol)} onToggle={() => toggleWatch(item.symbol)} /></article>) : <p>没有找到已验证的 A 股</p>}</div>}
    <div className="selector-tabs" role="tablist" aria-label="A 股候选分类">{tabs.map(([key, name]) => <button ref={(node) => { tabRefs.current[key] = node; }} id={`stock-selector-tab-${key === "short_term" ? "short" : key}`} key={key} role="tab" aria-controls="stock-selector-panel" aria-selected={tab === key} tabIndex={tab === key ? 0 : -1} type="button" onKeyDown={onTabKey} onClick={() => selectTab(key)}>{name}</button>)}</div>
    <div id="stock-selector-panel" role="tabpanel" aria-labelledby={`stock-selector-tab-${tab === "short_term" ? "short" : tab}`} className="stock-options">
      {candidateState === "loading" && <p className="selector-message"><LoaderCircle size={15} />正在读取候选池...</p>}
      {candidateState === "error" && <div className="selector-message error" role="alert"><ShieldAlert size={15} /><span>{candidateError}</span><button type="button" onClick={() => void refreshCandidates()}>重试候选</button></div>}
      {candidateState === "ready" && tab !== "watchlist" && candidateEntries.length === 0 && <div className="selector-empty"><b>{board?.universe_status === "empty" ? "本地候选池为空" : "当前分类暂无候选"}</b><p>{board?.universe_status === "empty" ? "同步足够历史数据后才会生成候选，不会自动猜测股票。" : "可通过代码或名称搜索选择 A 股。"}</p></div>}
      {tab === "watchlist" && watchlist.length === 0 && <div className="selector-empty"><b>暂无自选股</b><p>可从候选或搜索结果加入自选。</p></div>}
      {candidateEntries.map((entry) => <CandidateRow key={`${entry.horizon}-${entry.symbol}`} entry={entry} identity={identities[entry.symbol]} selected={selection.symbol === entry.symbol} watched={watchlist.includes(entry.symbol)} onSelect={() => selection.select(entry.symbol, "candidate")} onWatch={() => toggleWatch(entry.symbol)} />)}
      {tab === "watchlist" && watchlist.map((symbol) => <WatchlistRow key={symbol} symbol={symbol} item={identities[symbol]} error={identityErrors[symbol]} selected={selection.symbol === symbol} onSelect={() => selection.select(symbol, "watchlist")} onWatch={() => toggleWatch(symbol)} onRetry={() => retryIdentity(symbol)} />)}
    </div>
  </section>;
}
