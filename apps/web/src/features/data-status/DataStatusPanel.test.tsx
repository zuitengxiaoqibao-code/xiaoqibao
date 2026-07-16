import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataStatusPanel } from "./DataStatusPanel";

describe("DataStatusPanel", () => {
  it("shows actual source and written rows", () => {
    render(<DataStatusPanel state={{ kind: "ready", report: {
      symbol: "600000", state: "ready", written_rows: 20, source: "baidu",
      parquet_path: "600000.parquet", started_at: "2026-07-13T14:00:00",
      finished_at: "2026-07-13T14:01:00", message: "同步完成",
    } }} />);

    expect(screen.getByText("百度股市通")).toBeInTheDocument();
    expect(screen.getByText("20 条日线")).toBeInTheDocument();
  });

  it("shows source errors without data claims", () => {
    render(<DataStatusPanel state={{ kind: "error", message: "数据源超时" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("数据源超时");
  });
});
