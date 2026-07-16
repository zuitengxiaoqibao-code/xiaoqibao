import { Database, LoaderCircle, ShieldAlert } from "lucide-react";

import type { DataStatusState } from "./types";

const sourceNames: Record<string, string> = {
  baidu: "百度股市通",
  mootdx: "通达信 mootdx",
};

export function DataStatusPanel({ state }: { state: DataStatusState }) {
  if (state.kind === "idle") {
    return <div className="data-status empty"><Database size={17} /><span>尚未同步历史日线</span></div>;
  }
  if (state.kind === "syncing") {
    return <div className="data-status syncing" aria-busy="true"><LoaderCircle size={17} /><span>正在同步主备数据源...</span></div>;
  }
  if (state.kind === "error") {
    return <div className="data-status error" role="alert"><ShieldAlert size={17} /><span>{state.message}</span></div>;
  }
  return (
    <div className="data-status ready">
      <Database size={17} />
      <div><b>{state.report.written_rows} 条日线</b><span>{sourceNames[state.report.source] ?? state.report.source}</span></div>
    </div>
  );
}

