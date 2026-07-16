import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BeginnerNavigation, type BeginnerView } from "./BeginnerNavigation";

describe("BeginnerNavigation", () => {
  it("shows exactly the six beginner entries and a separate convertible-bond entry", () => {
    render(<BeginnerNavigation active="dashboard" onNavigate={vi.fn()} />);

    const navigation = screen.getByRole("navigation", { name: "主要功能" });
    expect(navigation).toHaveTextContent("今日研判A 股观察新闻热点风险提醒历史复盘数据设置");
    expect(navigation.querySelectorAll("button")).toHaveLength(6);
    expect(screen.getByRole("button", { name: "可转债" })).toBeInTheDocument();
    expect(screen.queryByText(/中书省|东厂|礼部|刑部|工部|部门/)).not.toBeInTheDocument();
  });

  it("reports the selected beginner route", () => {
    const onNavigate = vi.fn<(view: BeginnerView) => void>();
    render(<BeginnerNavigation active="dashboard" onNavigate={onNavigate} />);

    fireEvent.click(screen.getByRole("button", { name: "风险提醒" }));
    expect(onNavigate).toHaveBeenCalledWith("risk");
  });
});
