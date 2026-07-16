import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Dashboard } from "../dashboard/Dashboard";

const snapshot = () => new Promise<never>(() => undefined);

describe("governance navigation", () => {
  it("ignores a stale audit response after switching to compliance", async () => {
    let resolveAudit!: (value: { state: string; findings: never[] }) => void;
    const pendingAudit = new Promise<{ state: string; findings: never[] }>((resolve) => { resolveAudit = resolve; });
    render(<Dashboard
      loadSnapshot={snapshot}
      loadAudit={() => pendingAudit}
      loadCompliance={() => Promise.resolve({ policy_state: "current", sources: [], features: [] })}
    />);

    fireEvent.click(screen.getByRole("button", { name: /东厂/ }));
    fireEvent.click(screen.getByRole("button", { name: /礼部/ }));
    expect(await screen.findByRole("heading", { name: "来源权限与声明" })).toBeInTheDocument();

    resolveAudit({ state: "ready", findings: [] });
    await waitFor(() => expect(screen.getByRole("heading", { name: "来源权限与声明" })).toBeInTheDocument());
    expect(screen.queryByRole("heading", { name: "独立审计发现" })).not.toBeInTheDocument();
  });

  it("does not render loaded audit data through the compliance view", async () => {
    const pendingCompliance = new Promise<never>(() => undefined);
    render(<Dashboard
      loadSnapshot={snapshot}
      loadAudit={() => Promise.resolve({ state: "ready", findings: [] })}
      loadCompliance={() => pendingCompliance}
    />);

    fireEvent.click(screen.getByRole("button", { name: /东厂/ }));
    expect(await screen.findByRole("heading", { name: "独立审计发现" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /礼部/ }));

    expect(screen.getByText("正在加载...")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "独立审计发现" })).not.toBeInTheDocument();
  });

  it("switches to an independent Xingbu view", async () => {
    render(<Dashboard loadSnapshot={snapshot} loadRisk={() => Promise.resolve({
      rule_version: "2026-07-13.1", limits: { max_position: "0.20" },
    })} />);
    fireEvent.click(screen.getByRole("button", { name: /刑部/ }));
    expect(await screen.findByRole("heading", { name: "实时风控" })).toBeInTheDocument();
    expect(screen.getByText("已验证风险事件统一进入审计记录")).toBeInTheDocument();
    expect(screen.queryByText("A 股单标的侦测")).not.toBeInTheDocument();
  });

  it("shows explicit compliance actions without implying authorization", async () => {
    render(<Dashboard loadSnapshot={snapshot} loadCompliance={() => Promise.resolve({
      policy_state: "stale", sources: [{ source: "tencent", permission_state: "authorized", disclaimer_version: "2026-07", user_acknowledged_at: null }],
      features: [{ feature: "paper_orders", allowed: false, blocked_reasons: ["tencent:disclaimer_unacknowledged"] }],
    })} complianceAction={() => Promise.resolve()} />);
    fireEvent.click(screen.getByRole("button", { name: /礼部/ }));
    expect(await screen.findByRole("heading", { name: "来源权限与声明" })).toBeInTheDocument();
    expect(screen.getByText("政策需复核")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认声明" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "撤销授权" })).toBeInTheDocument();
  });

  it("renders empty and critical audit states with immutable snapshots", async () => {
    const { rerender } = render(<Dashboard loadSnapshot={snapshot} loadAudit={() => Promise.resolve({ state: "ready", findings: [] })} />);
    fireEvent.click(screen.getByRole("button", { name: /东厂/ }));
    expect(await screen.findByText("暂无审计发现")).toBeInTheDocument();

    rerender(<Dashboard loadSnapshot={snapshot} loadAudit={() => Promise.resolve({ state: "ready", findings: [{ finding_id: "audit-1", finding_type: "abnormal_rejection_rate", severity: "critical", owner_department: "xingbu", resolution_state: "open", evidence: ["snapshot://one"], snapshots: [{ snapshot_id: "one", evidence_link: "snapshot://one" }] }] })} />);
    expect(await screen.findByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText("snapshot://one")).toBeInTheDocument();
  });

  it("awaits compliance actions, refreshes status, and surfaces failures", async () => {
    let resolveAction!: () => void;
    const loadCompliance = vi.fn()
      .mockResolvedValueOnce({ policy_state: "current", sources: [{ source: "tencent", permission_state: "revoked", disclaimer_version: "2026-07", user_acknowledged_at: null }], features: [{ feature: "paper_orders", allowed: false, blocked_reasons: ["tencent:revoked"] }] })
      .mockResolvedValueOnce({ policy_state: "current", sources: [{ source: "tencent", permission_state: "revoked", disclaimer_version: "2026-07", user_acknowledged_at: "2026-07-13" }], features: [{ feature: "paper_orders", allowed: false, blocked_reasons: ["tencent:revoked"] }] });
    const action = vi.fn(() => new Promise<void>((resolve) => { resolveAction = resolve; }));
    render(<Dashboard loadSnapshot={snapshot} loadCompliance={loadCompliance} complianceAction={action} />);
    fireEvent.click(screen.getByRole("button", { name: /礼部/ }));
    fireEvent.click(await screen.findByRole("button", { name: "确认声明" }));
    expect(screen.getByRole("button", { name: "处理中..." })).toBeDisabled();
    resolveAction();
    expect(await screen.findByText(/已确认/)).toBeInTheDocument();
    expect(loadCompliance).toHaveBeenCalledTimes(2);
  });

  it("shows a compliance action failure", async () => {
    render(<Dashboard loadSnapshot={snapshot} loadCompliance={() => Promise.resolve({
      policy_state: "current", sources: [{ source: "tencent", permission_state: "revoked", disclaimer_version: "2026-07", user_acknowledged_at: null }],
      features: [{ feature: "paper_orders", allowed: false, blocked_reasons: ["tencent:revoked"] }],
    })} complianceAction={() => Promise.reject(new Error("授权服务不可用"))} />);
    fireEvent.click(screen.getByRole("button", { name: /礼部/ }));
    fireEvent.change(await screen.findByLabelText("tencent 权限依据"), { target: { value: "contract:test" } });
    fireEvent.click(await screen.findByRole("button", { name: "授权" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("授权服务不可用");
    expect(screen.getByRole("heading", { name: "来源权限与声明" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "授权" })).toBeEnabled();
  });

  it("retries an initial compliance load failure", async () => {
    const loadCompliance = vi.fn()
      .mockRejectedValueOnce(new Error("合规状态不可用"))
      .mockResolvedValueOnce({ policy_state: "current", sources: [], features: [] });
    render(<Dashboard loadSnapshot={snapshot} loadCompliance={loadCompliance} />);
    fireEvent.click(screen.getByRole("button", { name: /礼部/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("合规状态不可用");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("heading", { name: "来源权限与声明" })).toBeInTheDocument();
    expect(loadCompliance).toHaveBeenCalledTimes(2);
  });

  it("switches compliance records between A shares and convertible bonds", async () => {
    const loadCompliance = vi.fn((asset?: string) => Promise.resolve({ policy_state: "current",
      sources: [{ source: asset === "convertible_bond" ? "eastmoney" : "tencent", permission_state: "pending", disclaimer_version: "2026-07", user_acknowledged_at: null }], features: [] }));
    const action = vi.fn(() => Promise.resolve());
    render(<Dashboard loadSnapshot={snapshot} loadCompliance={loadCompliance} complianceAction={action} />);
    fireEvent.click(screen.getByRole("button", { name: /礼部/ }));
    fireEvent.click(await screen.findByRole("button", { name: "可转债" }));
    expect(await screen.findByText("eastmoney")).toBeInTheDocument();
    expect(loadCompliance).toHaveBeenLastCalledWith("convertible_bond");
  });
});
