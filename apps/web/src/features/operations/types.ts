export type OperationJob = { job_key: string; phase: "premarket" | "intraday" | "postclose"; trading_date: string; slot: string; trigger: "scheduled" | "manual"; attempt: number; attempts: number; status: "completed" | "failed"; occurred_at: string; report_id: string | null; error_code: string | null };
export type BackupRecord = { backup_id: string; created_at: string; file_count: number; total_bytes: number };
export type OperationsStatus = { scheduler: { paused: boolean; jobs: OperationJob[] }; backups: BackupRecord[] };
export type BackupVerification = { backup_id: string; valid: boolean; restore_drill_passed: boolean; checked_files: number; mismatched_files: string[] };
