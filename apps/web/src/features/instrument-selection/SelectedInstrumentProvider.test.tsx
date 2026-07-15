import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { SelectedInstrumentProvider, useSelectedInstrument } from "./SelectedInstrumentProvider";

function Probe() {
  const selection = useSelectedInstrument();
  return <>
    <output>{selection.symbol ?? "未选择"}</output>
    <output>{selection.source ?? "无来源"}</output>
    <button type="button" onClick={() => selection.select("000001", "search")}>选择 000001</button>
    <button type="button" onClick={() => selection.select("113065", "search")}>选择转债</button>
    <button type="button" onClick={selection.clear}>清除</button>
  </>;
}

describe("SelectedInstrumentProvider", () => {
  beforeEach(() => window.history.replaceState({}, "", "/"));

  it("restores the selected A-share from the symbol query parameter", () => {
    window.history.replaceState({}, "", "/?symbol=600000");
    render(<SelectedInstrumentProvider><Probe /></SelectedInstrumentProvider>);
    expect(screen.getByText("600000")).toBeInTheDocument();
    expect(screen.getByText("url")).toBeInTheDocument();
  });

  it("writes each explicit selection to browser history", () => {
    render(<SelectedInstrumentProvider><Probe /></SelectedInstrumentProvider>);
    fireEvent.click(screen.getByRole("button", { name: "选择 000001" }));
    expect(new URL(window.location.href).searchParams.get("symbol")).toBe("000001");
    expect(screen.getByText("search")).toBeInTheDocument();
  });

  it("restores forward and back navigation from the URL", () => {
    render(<SelectedInstrumentProvider><Probe /></SelectedInstrumentProvider>);
    fireEvent.click(screen.getByRole("button", { name: "选择 000001" }));
    window.history.pushState({}, "", "/?symbol=600000");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(screen.getByText("600000")).toBeInTheDocument();
    expect(screen.getByText("url")).toBeInTheDocument();
  });

  it("rejects non A-share symbols and ignores symbol state on the bond route", () => {
    const view = render(<SelectedInstrumentProvider><Probe /></SelectedInstrumentProvider>);
    fireEvent.click(screen.getByRole("button", { name: "选择转债" }));
    expect(screen.getByText("未选择")).toBeInTheDocument();
    window.history.replaceState({}, "", "/convertible-bonds?symbol=600000");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(screen.getByText("未选择")).toBeInTheDocument();
    view.unmount();
  });
});
