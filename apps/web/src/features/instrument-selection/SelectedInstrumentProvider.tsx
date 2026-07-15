import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";

export type SelectionSource = "candidate" | "search" | "watchlist" | "url";

type SelectedInstrument = {
  symbol: string | null;
  asset: "a_share";
  source: SelectionSource | null;
  selectedAt: string | null;
  select: (symbol: string, source: Exclude<SelectionSource, "url">) => void;
  clear: () => void;
};

const SelectedInstrumentContext = createContext<SelectedInstrument | null>(null);
const A_SHARE_SYMBOL = /^(?:(?:000|001|002|003|300|301|600|601|603|605|688|689|920)\d{3}|[48]\d{5})$/;

function symbolFromLocation(): string | null {
  if (window.location.pathname === "/convertible-bonds") return null;
  const symbol = new URL(window.location.href).searchParams.get("symbol");
  return symbol && A_SHARE_SYMBOL.test(symbol) ? symbol : null;
}

export function SelectedInstrumentProvider({ children }: { children: ReactNode }) {
  const initialSymbol = symbolFromLocation();
  const [state, setState] = useState<Pick<SelectedInstrument, "symbol" | "source" | "selectedAt">>({
    symbol: initialSymbol,
    source: initialSymbol ? "url" : null,
    selectedAt: initialSymbol ? new Date().toISOString() : null,
  });

  useEffect(() => {
    const restore = () => {
      const symbol = symbolFromLocation();
      setState({ symbol, source: symbol ? "url" : null, selectedAt: symbol ? new Date().toISOString() : null });
    };
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  const value = useMemo<SelectedInstrument>(() => ({
    ...state,
    asset: "a_share",
    select(symbol, source) {
      if (!A_SHARE_SYMBOL.test(symbol) || window.location.pathname === "/convertible-bonds") return;
      const url = new URL(window.location.href);
      url.searchParams.set("symbol", symbol);
      window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
      setState({ symbol, source, selectedAt: new Date().toISOString() });
    },
    clear() {
      const url = new URL(window.location.href);
      url.searchParams.delete("symbol");
      window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
      setState({ symbol: null, source: null, selectedAt: null });
    },
  }), [state]);

  return <SelectedInstrumentContext.Provider value={value}>{children}</SelectedInstrumentContext.Provider>;
}

export function useSelectedInstrument(): SelectedInstrument {
  const value = useContext(SelectedInstrumentContext);
  if (!value) throw new Error("useSelectedInstrument must be used inside SelectedInstrumentProvider");
  return value;
}
