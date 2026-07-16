import type { BackupRecord, BackupVerification, OperationsStatus } from "./types";

async function read<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail?.message ?? body.detail ?? `运维请求失败 (${response.status})`);
  }
  return response.json();
}

export const loadOperationsStatus = () => read<OperationsStatus>("/api/v1/operations/status");
export const setSchedulerPaused = (paused: boolean) => read<OperationsStatus["scheduler"]>(`/api/v1/operations/scheduler/${paused ? "pause" : "resume"}`, { method: "POST" });
export const createBackup = () => read<BackupRecord>("/api/v1/operations/backups", { method: "POST" });
export const verifyBackup = (backupId: string) => read<BackupVerification>(`/api/v1/operations/backups/${backupId}/verify?restore_drill=true`, { method: "POST" });
export const runManualJob = (phase: string, tradingDate: string) => read<{ report_id: string }>(`/api/v1/operations/jobs/${phase}/${tradingDate}/run`, { method: "POST" });
