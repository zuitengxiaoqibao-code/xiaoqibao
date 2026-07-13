import { useEffect, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  BookOpenCheck,
  CircleDollarSign,
  LoaderCircle,
  ShieldAlert,
  WalletCards,
} from "lucide-react";

import type { OrderResult, PaperAccount, Portfolio } from "./types";

type Props = {
  symbol: string;
  loadPortfolio: () => Promise<Portfolio>;
  createAccount: () => Promise<PaperAccount>;
  submitOrder: (symbol: string, side: "buy" | "sell", shares: number) => Promise<OrderResult>;
};

type PanelState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "ready"; portfolio: Portfolio }
  | { kind: "error"; message: string };

const reasonLabels: Record<string, string> = {
  insufficient_cash: "可用资金不足",
  single_position_cap: "超过单票 20% 上限",
  total_exposure_cap: "超过总仓位 80% 上限",
  quote_not_fresh: "行情已过期或不可用",
  risk_rejected: "刑部风控未通过",
  limit_up_buy: "涨停状态无法模拟买入",
  limit_down_sell: "跌停状态无法模拟卖出",
  source_unavailable: "行情源暂不可用，委托已留痕",
  risk_unavailable: "刑部风控暂不可用，委托已留痕",
};

function money(value: string): string {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(Number(value));
}

export function PaperTradingPanel({ symbol, loadPortfolio, createAccount, submitOrder }: Props) {
  const [state, setState] = useState<PanelState>({ kind: "loading" });
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [shares, setShares] = useState(100);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ kind: "filled" | "rejected"; message: string } | null>(null);

  async function refresh() {
    try {
      setState({ kind: "ready", portfolio: await loadPortfolio() });
    } catch (error) {
      const message = error instanceof Error ? error.message : "账户读取失败";
      setState(message.includes("不存在") ? { kind: "empty" } : { kind: "error", message });
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function openAccount() {
    setState({ kind: "loading" });
    try {
      await createAccount();
      await refresh();
    } catch (error) {
      setState({ kind: "error", message: error instanceof Error ? error.message : "开户失败" });
    }
  }

  async function placeOrder() {
    setSubmitting(true);
    setResult(null);
    try {
      const response = await submitOrder(symbol, side, shares);
      if (response.status === "filled") {
        setResult({ kind: "filled", message: "模拟成交已记录" });
        await refresh();
      } else {
        setResult({
          kind: "rejected",
          message: reasonLabels[response.reason ?? ""] ?? "委托已被规则拒绝",
        });
        await refresh();
      }
    } catch (error) {
      setResult({
        kind: "rejected",
        message: error instanceof Error ? error.message : "行情源暂不可用",
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="paper-panel">
      <div className="paper-heading">
        <div><p className="eyebrow">吏部 · 兵部 · 户部 / 联合作业区</p><h2>模拟交易与资金台账</h2></div>
        <span className="paper-badge"><ShieldAlert size={14} />仅纸面演练 · 不连接券商</span>
      </div>

      {state.kind === "loading" && <div className="paper-message" aria-busy="true"><LoaderCircle size={18} />正在核验模拟账户...</div>}
      {state.kind === "empty" && (
        <div className="paper-message paper-empty">
          <WalletCards size={25} /><div><b>尚未建立模拟账户</b><p>使用独立虚拟资金练习，真实资产不会受影响。</p></div>
          <button type="button" onClick={() => void openAccount()}>建立 10 万元模拟账户</button>
        </div>
      )}
      {state.kind === "error" && <div className="paper-message paper-error" role="alert"><ShieldAlert size={18} />{state.message}</div>}
      {state.kind === "ready" && (
        <div className="paper-grid">
          <section className="paper-unit allocation-unit">
            <div className="unit-title"><CircleDollarSign size={16} /><span><b>吏部</b><small>资金与仓位预算</small></span></div>
            <dl className="account-metrics">
              <div><dt>可用资金</dt><dd>¥{money(state.portfolio.account.cash)}</dd></div>
              <div><dt>总权益</dt><dd>¥{money(state.portfolio.account.total_equity)}</dd></div>
              <div><dt>当前仓位</dt><dd>{(Number(state.portfolio.account.exposure) * 100).toFixed(1)}%</dd></div>
            </dl>
            <div className="exposure-track"><span style={{ width: `${Math.min(100, Number(state.portfolio.account.exposure) * 100)}%` }} /></div>
            <p className="limit-note">单票 ≤ 20% · 总仓位 ≤ 80%</p>
            <div className="positions-list">
              {state.portfolio.positions.length === 0 ? <p>暂无持仓</p> : state.portfolio.positions.map((position) => (
                <div key={position.symbol}><b>{position.symbol}</b><span>{position.shares} 股</span><small>市值 ¥{money(position.market_value)}</small></div>
              ))}
            </div>
          </section>

          <section className="paper-unit order-unit">
            <div className="unit-title"><BookOpenCheck size={16} /><span><b>兵部</b><small>模拟委托执行</small></span></div>
            <div className="order-symbol"><span>当前标的</span><b>{symbol}</b></div>
            <div className="side-control" aria-label="买卖方向">
              <button className={side === "buy" ? "active buy" : ""} type="button" onClick={() => setSide("buy")}><ArrowDownToLine size={15} />买入</button>
              <button className={side === "sell" ? "active sell" : ""} type="button" onClick={() => setSide("sell")}><ArrowUpFromLine size={15} />卖出</button>
            </div>
            <label className="shares-field">委托数量（100 股整数手）<input min={100} max={1000000} step={100} type="number" value={shares} onChange={(event) => setShares(Math.max(100, Number(event.target.value)))} /></label>
            <button className="submit-paper-order" disabled={submitting || symbol.length !== 6 || shares % 100 !== 0} type="button" onClick={() => void placeOrder()}>
              {submitting ? <LoaderCircle size={16} /> : side === "buy" ? <ArrowDownToLine size={16} /> : <ArrowUpFromLine size={16} />}
              {submitting ? "执行规则核验..." : `提交模拟${side === "buy" ? "买入" : "卖出"}`}
            </button>
            {result && <div className={`order-result ${result.kind}`} role={result.kind === "filled" ? "status" : "alert"}>{result.kind === "filled" ? <BookOpenCheck size={15} /> : <ShieldAlert size={15} />}{result.message}</div>}
          </section>

          <section className="paper-unit ledger-unit">
            <div className="unit-title"><WalletCards size={16} /><span><b>户部</b><small>委托与现金流水</small></span></div>
            <div className="audit-list">
              {state.portfolio.orders.length === 0 && state.portfolio.ledger.length <= 1 ? <p className="no-audit">暂无交易记录</p> : state.portfolio.orders.slice().reverse().slice(0, 5).map((item) => (
                <div className="audit-row" key={item.order_id}>
                  <span className={`audit-state ${item.status}`} />
                  <div><b>{item.symbol} · {item.side === "buy" ? "买入" : "卖出"} {item.shares} 股</b><small>{item.status === "filled" ? "已成交并入账" : reasonLabels[item.rejection_reason ?? ""] ?? "等待执行"}</small></div>
                  <em>{item.status.toUpperCase()}</em>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
