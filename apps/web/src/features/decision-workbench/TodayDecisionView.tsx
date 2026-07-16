import { Search } from "lucide-react";
import { useState } from "react";

import { DecisionWorkbench } from "./DecisionWorkbench";
import type { DecisionResponse } from "./types";

type Props = {
  loadCurrent: () => Promise<DecisionResponse>;
  loadDate?: (date: string) => Promise<DecisionResponse>;
  selectedSymbol?: string | null;
  onOpenAShares?: () => void;
};

export function TodayDecisionView({ loadCurrent, loadDate, selectedSymbol, onOpenAShares }: Props) {
  const [scope, setScope] = useState<"market" | "selected">("market");
  const selectedScope = scope === "selected" && Boolean(selectedSymbol);

  return <div className="today-decision-view">
    <section className="decision-scope" aria-label="研判范围">
      <div>
        <span>研判范围</span>
        <strong>{selectedScope ? `A 股 ${selectedSymbol}` : "全部 A 股建议"}</strong>
        <p>{selectedScope ? "只显示当前股票已有的可验证结论" : "汇总今日已生成的盘前、盘中与盘后记录"}</p>
      </div>
      <div className="decision-scope-switch" role="group" aria-label="切换研判范围">
        <button type="button" aria-pressed={!selectedScope} onClick={() => setScope("market")}>全市场</button>
        {selectedSymbol
          ? <button type="button" aria-pressed={selectedScope} onClick={() => setScope("selected")}>只看 {selectedSymbol}</button>
          : onOpenAShares && <button type="button" onClick={onOpenAShares}><Search size={15} />选择股票</button>}
      </div>
    </section>
    <DecisionWorkbench loadCurrent={loadCurrent} loadDate={loadDate} selectedSymbol={selectedScope ? selectedSymbol : undefined} />
  </div>;
}
