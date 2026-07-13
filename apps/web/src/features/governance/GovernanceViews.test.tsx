import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Dashboard } from "../dashboard/Dashboard";

const snapshot = () => new Promise<never>(() => undefined);

describe("governance navigation", () => {
  it("switches to an independent Xingbu view", async () => {
    render(<Dashboard loadSnapshot={snapshot} loadRisk={() => Promise.resolve({
      rule_version: "2026-07-13.1", limits: { max_position: "0.20" },
      recent_rejections: [{ decision_id: "risk-1", order_id: "order-1", symbol: "600000", outcome: "reject", reason_code: "source_unavailable", rule_version: "system.1", decided_at: "2026-07-13T10:00:00Z" }],
    })} />);
    fireEvent.click(screen.getByRole("button", { name: /刑部/ }));
    expect(await screen.findByRole("heading", { name: "实时风控" })).toBeInTheDocument();
    expect(screen.getByText(/source_unavailable/)).toBeInTheDocument();
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
});
