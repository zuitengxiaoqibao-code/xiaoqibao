import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Dashboard } from "./Dashboard";

const freshCard = {
  symbol: "600000",
  asset: "a_share" as const,
  action: "observe" as const,
  change_percent: "1.49",
  quality: "fresh" as const,
  invalid_reasons: [],
  evidence: [
    {
      label: "最新价",
      value: "10.25",
      source: "tencent",
      observed_at: "2026-07-13T10:30:00",
    },
  ],
};

describe("Dashboard", () => {
  it("navigates to the independent convertible-bond domain", async () => {
    render(<Dashboard loadSnapshot={() => Promise.resolve(freshCard)}
      loadBondDashboard={() => Promise.resolve({ status: "empty", bond_count: 0, bond_codes: [] })}
      loadBondDiagnosis={() => Promise.reject(new Error("unused"))}
      loadBondCandidates={() => Promise.resolve({ status: "empty", items: [] })} />);

    fireEvent.click(screen.getByRole("button", { name: /可转债专区/ }));

    expect(await screen.findByRole("heading", { name: "可转债专区" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "今日情报态势" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "候选池" })).toBeInTheDocument();
  });

  it("shows evidence source and data time", async () => {
    render(<Dashboard loadSnapshot={() => Promise.resolve(freshCard)} />);

    fireEvent.click(screen.getByRole("button", { name: "调取行情" }));

    expect(await screen.findByText("腾讯行情")).toBeInTheDocument();
    expect(screen.getByText(/数据截至/)).toBeInTheDocument();
    expect(screen.getByText("600000")).toBeInTheDocument();
  });

  it("makes a blocked signal explicit", async () => {
    const blockedCard = {
      ...freshCard,
      action: "blocked" as const,
      quality: "stale" as const,
      invalid_reasons: ["数据已过期或质量异常"],
    };
    render(<Dashboard loadSnapshot={() => Promise.resolve(blockedCard)} />);

    fireEvent.click(screen.getByRole("button", { name: "调取行情" }));

    expect(await screen.findByRole("status")).toHaveTextContent("仅观察");
    expect(screen.getByText("数据已过期或质量异常")).toBeInTheDocument();
  });

  it("shows a loading state before the request completes", () => {
    render(<Dashboard loadSnapshot={() => new Promise(() => undefined)} />);

    fireEvent.click(screen.getByRole("button", { name: "调取行情" }));

    expect(screen.getByText("正在调取工部行情...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "调取行情" })).toBeDisabled();
  });

  it("surfaces network errors without inventing data", async () => {
    render(<Dashboard loadSnapshot={() => Promise.reject(new Error("行情源暂不可用"))} />);

    fireEvent.click(screen.getByRole("button", { name: "调取行情" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("行情源暂不可用");
  });

  it("passes the entered six-digit symbol to the API", async () => {
    const loadSnapshot = vi.fn(() => Promise.resolve(freshCard));
    render(<Dashboard loadSnapshot={loadSnapshot} />);

    fireEvent.change(screen.getByLabelText("A 股代码"), { target: { value: "000001" } });
    fireEvent.click(screen.getByRole("button", { name: "调取行情" }));

    await screen.findByText("腾讯行情");
    expect(loadSnapshot).toHaveBeenCalledWith("000001");
  });
});
