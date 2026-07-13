import { Play, ShieldAlert } from "lucide-react";
import { useState } from "react";

import type { BacktestResult } from "./types";

type State = { kind: "idle" | "loading" } | { kind: "ready"; result: BacktestResult } | { kind: "error"; message: string };

function percent(value: string): string {
  return `${(Number(value) * 100).toFixed(2)}%`;
}

export function BacktestPanel({ symbol, runBacktest }: { symbol: string; runBacktest: (symbol: string) => Promise<BacktestResult> }) {
  const [state, setState] = useState<State>({ kind: "idle" });
  async function run() {
    setState({ kind: "loading" });
    try { setState({ kind: "ready", result: await runBacktest(symbol) }); }
    catch (error) { setState({ kind: "error", message: error instanceof Error ? error.message : "未知错误" }); }
  }
  return (
    <section className="backtest-panel">
      <div className="backtest-heading">
        <div><p className="eyebrow">中书省 / 固定策略模板</p><h2>双均线历史回测</h2><p>5 日快线 × 20 日慢线 · 次日开盘成交 · 已计佣金与滑点</p></div>
        <button type="button" onClick={() => void run()} disabled={state.kind === "loading"}><Play size={15} />运行回测</button>
      </div>
      {state.kind === "idle" && <div className="backtest-empty">使用本地历史日线，不调用 AI，不承诺收益。</div>}
      {state.kind === "loading" && <div className="backtest-empty" aria-busy="true">正在复算历史交易...</div>}
      {state.kind === "error" && <div className="backtest-error" role="alert"><ShieldAlert size={17} />{state.message}</div>}
      {state.kind === "ready" && <div className="metric-grid">
        <div><span>总收益</span><b className={Number(state.result.total_return) < 0 ? "negative-metric" : "positive-metric"}>{percent(state.result.total_return)}</b></div>
        <div><span>最大回撤</span><b>{percent(state.result.max_drawdown)}</b></div>
        <div><span>交易成本</span><b>{state.result.total_cost}</b></div>
        <div><span>成交次数</span><b>{state.result.trades.length} 笔</b></div>
      </div>}
    </section>
  );
}

