import { BarChart3, Play, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { isAShareSymbol } from "../instrument-selection/SelectedInstrumentProvider";
import type { BacktestResult } from "./types";

type State = { kind: "idle" | "loading" } | { kind: "ready"; result: BacktestResult } | { kind: "error"; message: string };

function percent(value: string): string {
  return `${(Number(value) * 100).toFixed(2)}%`;
}

const segmentName = { train: "训练段", validation: "验证段", out_of_sample: "样本外" };
const regimeName = { bull: "上行阶段", bear: "下行阶段", sideways: "震荡阶段" };

export function BacktestPanel({ symbol, runBacktest }: { symbol: string; runBacktest: (symbol: string, signal?: AbortSignal) => Promise<BacktestResult> }) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const [requestedSymbol, setRequestedSymbol] = useState(symbol);
  const explicitlyEdited = useRef(false);
  const requestVersion = useRef(0);
  const controller = useRef<AbortController | null>(null);
  function invalidateResult() {
    requestVersion.current += 1;
    controller.current?.abort(); controller.current = null;
    setState({ kind: "idle" });
  }
  useEffect(() => {
    if (!explicitlyEdited.current) { setRequestedSymbol(symbol); invalidateResult(); }
  }, [symbol]);
  useEffect(() => () => { requestVersion.current += 1; controller.current?.abort(); }, []);
  async function run() {
    if (!isAShareSymbol(requestedSymbol)) return;
    const request = ++requestVersion.current;
    controller.current?.abort();
    const currentController = new AbortController();
    controller.current = currentController;
    setState({ kind: "loading" });
    try { const result = await runBacktest(requestedSymbol, currentController.signal); if (request === requestVersion.current) setState({ kind: "ready", result }); }
    catch (error) { if (request === requestVersion.current && !currentController.signal.aborted) setState({ kind: "error", message: error instanceof Error ? error.message : "未知错误" }); }
    finally { if (request === requestVersion.current) controller.current = null; }
  }
  return (
    <section className="backtest-panel">
      <div className="backtest-heading">
        <div><p className="eyebrow">中书省 / 固定策略模板</p><h2>双均线历史回测</h2><p>5 日快线 × 20 日慢线 · 次日开盘成交 · 已计佣金与滑点</p></div>
        <label>回测 A 股代码<input aria-label="回测 A 股代码" inputMode="numeric" maxLength={6} pattern="\d{6}" value={requestedSymbol} onChange={(event) => { explicitlyEdited.current = true; setRequestedSymbol(event.target.value.replace(/\D/g, "")); invalidateResult(); }} /></label>
        <button type="button" onClick={() => void run()} disabled={state.kind === "loading" || !isAShareSymbol(requestedSymbol)}><Play size={15} />运行回测</button>
      </div>
      {state.kind === "idle" && <div className="backtest-empty">使用本地历史日线，不调用 AI，不承诺收益。</div>}
      {state.kind === "loading" && <div className="backtest-empty" aria-busy="true">正在复算历史交易...</div>}
      {state.kind === "error" && <div className="backtest-error" role="alert"><ShieldAlert size={17} />{state.message}</div>}
      {state.kind === "ready" && <div className="backtest-result"><p className="backtest-result-symbol">回测标的 {state.result.symbol}</p>
        <div className="metric-grid">
          <div><span>总收益</span><b className={Number(state.result.total_return) < 0 ? "negative-metric" : "positive-metric"}>{percent(state.result.total_return)}</b></div>
          <div><span>最大回撤</span><b>{percent(state.result.max_drawdown)}</b></div>
          <div><span>年化波动率</span><b>{percent(state.result.metrics.annualized_volatility)}</b></div>
          <div><span>闭合交易胜率</span><b>{percent(state.result.metrics.win_rate)}</b></div>
          <div><span>盈亏比</span><b>{state.result.metrics.profit_loss_ratio === null ? "--" : Number(state.result.metrics.profit_loss_ratio).toFixed(2)}</b></div>
          <div><span>换手率</span><b>{percent(state.result.metrics.turnover_rate)}</b></div>
          <div><span>交易成本</span><b>{state.result.total_cost}</b></div>
          <div><span>成交次数</span><b>{state.result.trades.length} 笔</b></div>
        </div>
        {state.result.segments.length > 0 && <section className="segment-analysis">
          <header><div><p className="eyebrow">STABILITY CHECK</p><h3>样本稳定性</h3></div><small>固定参数的连续时间切片；反复调参会使样本外结论失效</small></header>
          <div className="segment-table" role="table" aria-label="回测样本分段">
            {state.result.segments.map((segment) => <div role="row" key={segment.name} className={segment.name === "out_of_sample" ? "emphasis" : ""}>
              <span>{segmentName[segment.name]}</span><time>{segment.start_date} 至 {segment.end_date}</time><b className={Number(segment.total_return) < 0 ? "negative-metric" : "positive-metric"}>{percent(segment.total_return)}</b><small>回撤 {percent(segment.max_drawdown)} · {segment.bar_count} 日</small>
            </div>)}
          </div>
        </section>}
        <section className="regime-analysis">
          <header><BarChart3 size={16}/><div><h3>市场阶段归因</h3><small>仅使用当日及过去 20 日行情分类，不参与信号生成</small></div></header>
          <div>{state.result.market_regimes.map((regime) => <div key={regime.name}><span>{regimeName[regime.name]}</span><b className={Number(regime.total_return) < 0 ? "negative-metric" : "positive-metric"}>{percent(regime.total_return)}</b><small>{regime.bar_count} 个交易日</small></div>)}</div>
        </section>
      </div>}
    </section>
  );
}
