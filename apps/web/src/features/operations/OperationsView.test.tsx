import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OperationsView } from "./OperationsView";
import type { OperationsStatus } from "./types";


const status: OperationsStatus = {
  scheduler: {
    paused: false,
    jobs: [
      { job_key: "2026-07-14:premarket:0920", phase: "premarket", trading_date: "2026-07-14", slot: "0920", trigger: "scheduled", attempt: 2, attempts: 2, status: "completed", occurred_at: "2026-07-14T01:20:00Z", report_id: "report-1", error_code: null },
      { job_key: "2026-07-14:intraday:1030", phase: "intraday", trading_date: "2026-07-14", slot: "1030", trigger: "scheduled", attempt: 3, attempts: 3, status: "failed", occurred_at: "2026-07-14T02:30:00Z", report_id: null, error_code: "runtime_error" },
    ],
  },
  backups: [
    { backup_id: "backup-20260714", created_at: "2026-07-14T08:00:00Z", file_count: 8, total_bytes: 1048576 },
  ],
};


describe("OperationsView", () => {
  it("shows scheduler failures and verifies a backup with restore drill", async () => {
    const verifyBackup = vi.fn(() => Promise.resolve({ backup_id: "backup-20260714", valid: true, restore_drill_passed: true, checked_files: 8, mismatched_files: [] }));
    render(<OperationsView loadStatus={() => Promise.resolve(status)} setSchedulerPaused={() => Promise.resolve(status.scheduler)} createBackup={() => Promise.resolve(status.backups[0])} verifyBackup={verifyBackup} runManualJob={() => Promise.resolve({ report_id: "report-manual" })} />);

    expect(await screen.findByRole("heading", { name: "数据与运维中心" })).toBeInTheDocument();
    expect(screen.getByText("runtime_error")).toBeInTheDocument();
    expect(screen.getByText("累计尝试 3 次")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "执行恢复演练" }));
    expect(await screen.findByText("恢复演练通过")).toBeInTheDocument();
    expect(verifyBackup).toHaveBeenCalledWith("backup-20260714");
  });

  it("pauses scheduler and supports manual postclose recovery", async () => {
    const setSchedulerPaused = vi.fn(() => Promise.resolve({ ...status.scheduler, paused: true }));
    const runManualJob = vi.fn(() => Promise.resolve({ report_id: "report-manual" }));
    render(<OperationsView loadStatus={() => Promise.resolve(status)} setSchedulerPaused={setSchedulerPaused} createBackup={() => Promise.resolve(status.backups[0])} verifyBackup={() => Promise.reject(new Error("unused"))} runManualJob={runManualJob} />);
    await screen.findByRole("heading", { name: "数据与运维中心" });

    fireEvent.click(screen.getByRole("button", { name: "暂停调度" }));
    expect(await screen.findByText("调度已暂停")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("补跑交易日"), { target: { value: "2026-07-14" } });
    fireEvent.click(screen.getByRole("button", { name: "补跑盘后" }));
    expect(await screen.findByText("补跑已归档 report-manual")).toBeInTheDocument();
    expect(runManualJob).toHaveBeenCalledWith("postclose", "2026-07-14");
  });
});
