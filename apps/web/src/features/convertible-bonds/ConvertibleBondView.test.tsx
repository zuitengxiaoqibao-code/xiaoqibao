import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConvertibleBondView } from "./ConvertibleBondView";

const diagnosis = {
  status: "stale_quote" as const,
  bond: { code: "113065", name: "测试转债", price: "121.50", suspended: false },
  linked_stock: { code: "600001", name: "测试股份", price: "10.25", source: "tencent", observed_at: "2026-07-14T02:30:00Z" },
  quote: { source: "tencent", observed_at: "2026-07-14T02:30:00Z", quality: "stale" },
  clause_snapshot: { source: "eastmoney", fetched_at: "2026-07-14T02:30:00Z", conversion_price: "12.34", maturity: "2028-09-15", remaining_size: "18.765432" },
  metrics: { conversion_value: "83.063", conversion_premium: "0.4627", pure_bond_premium: null, remaining_term: { days: 794 } },
  risk: { outcome: "observe_only", unknowns: ["pure_bond_value", "turnover_amount"], explanations: ["bond_liquidity_missing"] },
  strong_redemption: { state: "announced", clause_text: "发行人已发布提前赎回公告", source: "eastmoney", observed_at: "2026-07-14T02:30:00Z" },
};

describe("ConvertibleBondView", () => {
  it("shows stale quote and evidence-backed strong redemption without invented values", async () => {
    render(<ConvertibleBondView loadDashboard={() => Promise.resolve({ status: "empty", bond_count: 0, bond_codes: [] })}
      loadDiagnosis={() => Promise.resolve(diagnosis)} loadCandidates={() => Promise.resolve({ status: "empty", items: [] })} />);
    fireEvent.click(screen.getByRole("tab", { name: "诊断" }));
    fireEvent.click(screen.getByRole("button", { name: "诊断转债" }));
    expect(await screen.findByText("行情已过期")).toBeInTheDocument();
    expect(screen.getByText("强赎已公告")).toBeInTheDocument();
    expect(screen.getByText(/发行人已发布/)).toBeInTheDocument();
    expect(screen.getByText("未知（缺少纯债价值）")).toBeInTheDocument();
  });

  it("shows authorization errors and source conflicts", async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error("可转债数据源尚未授权：tencent")).mockResolvedValueOnce({ ...diagnosis, status: "source_conflict" });
    const props = { loadDashboard: () => Promise.resolve({ status: "empty" as const, bond_count: 0, bond_codes: [] }), loadDiagnosis: load, loadCandidates: () => Promise.resolve({ status: "empty" as const, items: [] }) };
    const { unmount } = render(<ConvertibleBondView {...props} />);
    fireEvent.click(screen.getByRole("tab", { name: "诊断" })); fireEvent.click(screen.getByRole("button", { name: "诊断转债" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("数据源尚未配置，请在数据设置中检查连接。");
    expect(screen.queryByText("尚未授权")).not.toBeInTheDocument();
    unmount(); render(<ConvertibleBondView {...props} />);
    fireEvent.click(screen.getByRole("tab", { name: "诊断" })); fireEvent.click(screen.getByRole("button", { name: "诊断转债" }));
    expect(await screen.findByText("数据源冲突")).toBeInTheDocument();
  });
});
