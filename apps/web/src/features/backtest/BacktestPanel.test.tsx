import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BacktestPanel } from "./BacktestPanel";

const result = {
  symbol: "600000", strategy: "sma_cross", initial_cash: "100000",
  ending_equity: "76206.79", total_return: "-0.2379", max_drawdown: "0.2520",
  total_cost: "937.21", trades: Array.from({ length: 14 }, () => ({})),
  metrics: { annualized_volatility: "0.1825", win_rate: "0.4286", profit_loss_ratio: "1.2400", turnover_rate: "3.2500", closed_trade_count: 7 },
  segments: [
    { name: "train" as const, start_date: "2024-01-01", end_date: "2024-12-31", bar_count: 240, starting_equity: "100000", ending_equity: "110000", total_return: "0.1000", max_drawdown: "0.1200" },
    { name: "validation" as const, start_date: "2025-01-01", end_date: "2025-04-30", bar_count: 80, starting_equity: "110000", ending_equity: "107800", total_return: "-0.0200", max_drawdown: "0.0800" },
    { name: "out_of_sample" as const, start_date: "2025-05-01", end_date: "2025-08-31", bar_count: 80, starting_equity: "107800", ending_equity: "111034", total_return: "0.0300", max_drawdown: "0.0600" },
  ],
  market_regimes: [
    { name: "bull" as const, bar_count: 120, total_return: "0.1200" },
    { name: "bear" as const, bar_count: 90, total_return: "-0.1800" },
    { name: "sideways" as const, bar_count: 170, total_return: "0.0100" },
  ],
  equity_curve: [], warnings: [],
};

describe("BacktestPanel", () => {
  it("shows losses, drawdown and costs without positive framing", async () => {
    render(<BacktestPanel symbol="600000" runBacktest={() => Promise.resolve(result)} />);

    fireEvent.click(screen.getByRole("button", { name: "运行回测" }));

    expect(await screen.findByText("-23.79%")).toBeInTheDocument();
    expect(screen.getByText("25.20%")).toBeInTheDocument();
    expect(screen.getByText("937.21")).toBeInTheDocument();
    expect(screen.getByText("14 笔")).toBeInTheDocument();
    expect(screen.getByText("18.25%")).toBeInTheDocument();
    expect(screen.getByText("42.86%")).toBeInTheDocument();
    expect(screen.getByText("1.24")).toBeInTheDocument();
    expect(screen.getByText("325.00%")).toBeInTheDocument();
    expect(screen.getByText("样本外")).toBeInTheDocument();
    expect(screen.getByText("3.00%")).toBeInTheDocument();
    expect(screen.getByText("下行阶段")).toBeInTheDocument();
    expect(screen.getByText("-18.00%")).toBeInTheDocument();
  });

  it("asks for history sync when API returns a conflict", async () => {
    render(<BacktestPanel symbol="600000" runBacktest={() => Promise.reject(new Error("请先同步历史日线"))} />);
    fireEvent.click(screen.getByRole("button", { name: "运行回测" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请先同步历史日线");
  });
});
