import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PaperTradingPanel } from "./PaperTradingPanel";

const emptyPortfolio = {
  account: {
    account_id: "default",
    initial_cash: "100000",
    cash: "100000",
    total_equity: "100000",
    exposure: "0",
  },
  positions: [],
  ledger: [],
  orders: [],
};

describe("PaperTradingPanel", () => {
  it("offers to create an account when none exists", async () => {
    const loadPortfolio = vi.fn(() => Promise.reject(new Error("模拟账户不存在")));
    render(
      <PaperTradingPanel
        symbol="600000"
        loadPortfolio={loadPortfolio}
        createAccount={() => Promise.resolve(emptyPortfolio.account)}
        submitOrder={() => Promise.reject(new Error("unused"))}
      />,
    );

    expect(await screen.findByText("尚未建立模拟账户")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "建立 10 万元模拟账户" })).toBeInTheDocument();
  });

  it("shows filled result and refreshes the portfolio", async () => {
    const loadPortfolio = vi.fn(() => Promise.resolve(emptyPortfolio));
    const submitOrder = vi.fn(() =>
      Promise.resolve({ order_id: "order-1", status: "filled" as const, reason: null }),
    );
    render(
      <PaperTradingPanel
        symbol="600000"
        loadPortfolio={loadPortfolio}
        createAccount={() => Promise.resolve(emptyPortfolio.account)}
        submitOrder={submitOrder}
      />,
    );

    await screen.findByText("可用资金");
    fireEvent.click(screen.getByRole("button", { name: "提交模拟买入" }));

    expect(await screen.findByRole("status")).toHaveTextContent("模拟成交已记录");
    expect(submitOrder).toHaveBeenCalledWith("600000", "buy", 100);
    expect(loadPortfolio).toHaveBeenCalledTimes(2);
  });

  it("explains rejected and unavailable orders", async () => {
    const rejectedPortfolio = {
      ...emptyPortfolio,
      orders: [{
        order_id: "order-2",
        symbol: "600000",
        side: "buy" as const,
        shares: 100,
        status: "rejected" as const,
        rejection_reason: "insufficient_cash",
      }],
    };
    const loadPortfolio = vi.fn()
      .mockResolvedValueOnce(emptyPortfolio)
      .mockResolvedValueOnce(rejectedPortfolio);
    const submitOrder = vi.fn(() =>
      Promise.resolve({
        order_id: "order-2",
        status: "rejected" as const,
        reason: "insufficient_cash",
      }),
    );
    render(
      <PaperTradingPanel
        symbol="600000"
        loadPortfolio={loadPortfolio}
        createAccount={() => Promise.resolve(emptyPortfolio.account)}
        submitOrder={submitOrder}
      />,
    );

    await screen.findByText("可用资金");
    fireEvent.click(screen.getByRole("button", { name: "提交模拟买入" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("可用资金不足");
    expect(screen.getByText("600000 · 买入 100 股")).toBeInTheDocument();
    expect(screen.getByText("可用资金不足", { selector: "small" })).toBeInTheDocument();
  });
});
