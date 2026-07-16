export type SyncReport = {
  symbol: string;
  state: "ready" | "error" | "empty";
  written_rows: number;
  source: string;
  parquet_path: string | null;
  started_at: string;
  finished_at: string;
  message: string;
};

export type DataStatusState =
  | { kind: "idle" }
  | { kind: "syncing" }
  | { kind: "ready"; report: SyncReport }
  | { kind: "error"; message: string };

