import { Dashboard } from "../features/dashboard/Dashboard";
import { loadSnapshot } from "../features/dashboard/api";
import { syncHistory } from "../features/data-status/api";
import { createPaperAccount, loadPaperPortfolio, submitPaperOrder } from "../features/paper-trading/api";
import { runBacktest } from "../features/backtest/api";
import { complianceAction, loadAudit, loadCompliance, loadRisk } from "../features/governance/api";
import { loadBondCandidates, loadBondDashboard, loadBondDiagnosis } from "../features/convertible-bonds/api";

export function App() {
  return <Dashboard
    loadSnapshot={loadSnapshot}
    syncHistory={syncHistory}
    runBacktest={runBacktest}
    loadPaperPortfolio={loadPaperPortfolio}
    createPaperAccount={createPaperAccount}
    submitPaperOrder={submitPaperOrder}
    loadRisk={loadRisk} loadCompliance={loadCompliance} loadAudit={loadAudit} complianceAction={complianceAction}
    loadBondDashboard={loadBondDashboard} loadBondDiagnosis={loadBondDiagnosis} loadBondCandidates={loadBondCandidates}
  />;
}
