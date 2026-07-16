import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BeginnerRiskView } from "./BeginnerRiskView";

describe("BeginnerRiskView", () => {
  it("loads a plain-language risk status without internal rules or order concepts", async () => {
    render(<BeginnerRiskView load={() => Promise.resolve({ rule_version: "internal-v9", limits: { max_position: "0.2" } })} />);
    expect(await screen.findByText("风险检查正常运行")).toBeInTheDocument();
    expect(screen.queryByText(/internal-v9|max_position|仓位|委托|订单|刑部/)).not.toBeInTheDocument();
  });
  it("retries a failed request", async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error("风险数据暂不可用")).mockResolvedValueOnce({ rule_version: "v1", limits: {} });
    render(<BeginnerRiskView load={load} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("风险数据暂不可用");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("风险检查正常运行")).toBeInTheDocument();
  });
  it("ignores an older response after the loader changes", async () => {
    let resolveOld!: (value: { rule_version: string; limits: Record<string, string> }) => void;
    const old = new Promise<{ rule_version: string; limits: Record<string, string> }>((resolve) => { resolveOld = resolve; });
    const view = render(<BeginnerRiskView load={() => old} />);
    view.rerender(<BeginnerRiskView load={() => Promise.reject(new Error("最新风险请求失败"))} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("最新风险请求失败");
    resolveOld({ rule_version: "old", limits: {} });
    expect(screen.queryByText("风险检查正常运行")).not.toBeInTheDocument();
  });
});
