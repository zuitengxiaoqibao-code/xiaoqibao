import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BacktestPanel } from "./BacktestPanel";

const result = {
  symbol: "600000", strategy: "sma_cross", initial_cash: "100000",
  ending_equity: "76206.79", total_return: "-0.2379", max_drawdown: "0.2520",
  total_cost: "937.21", trades: Array.from({ length: 14 }, () => ({})),
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
  });

  it("asks for history sync when API returns a conflict", async () => {
    render(<BacktestPanel symbol="600000" runBacktest={() => Promise.reject(new Error("请先同步历史日线"))} />);
    fireEvent.click(screen.getByRole("button", { name: "运行回测" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请先同步历史日线");
  });
});
