import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GovernanceView, type ComplianceStatus } from "./GovernanceViews";

const status: ComplianceStatus = {
  policy_state: "current",
  sources: [{ source: "公开数据源", permission_state: "pending", disclaimer_version: "v1", user_acknowledged_at: null }],
  features: [],
};

describe("GovernanceView retained compliance flow", () => {
  it("loads A-share and convertible-bond settings independently", async () => {
    const loadCompliance = vi.fn().mockResolvedValue(status);
    render(<GovernanceView view="libu" loadCompliance={loadCompliance} />);
    await screen.findByText("公开数据源");
    fireEvent.click(screen.getByRole("button", { name: "可转债" }));
    expect(await screen.findByRole("button", { name: "可转债", pressed: true })).toBeInTheDocument();
    expect(loadCompliance).toHaveBeenLastCalledWith("convertible_bond");
  });

  it("keeps a failed compliance action retryable and completes on retry", async () => {
    const loadCompliance = vi.fn().mockResolvedValue(status);
    const complianceAction = vi.fn().mockRejectedValueOnce(new Error("授权暂不可用")).mockResolvedValueOnce(undefined);
    render(<GovernanceView view="libu" loadCompliance={loadCompliance} complianceAction={complianceAction} />);
    await screen.findByText("公开数据源");
    fireEvent.change(screen.getByLabelText("公开数据源 权限依据"), { target: { value: "公开许可说明" } });
    fireEvent.click(screen.getByRole("button", { name: "授权" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("授权暂不可用");
    fireEvent.click(screen.getByRole("button", { name: "授权" }));
    expect(await screen.findByText("公开数据源")).toBeInTheDocument();
    expect(complianceAction).toHaveBeenCalledTimes(2);
  });
});
