import { Dashboard } from "../features/dashboard/Dashboard";
import { loadSnapshot } from "../features/dashboard/api";
import { syncHistory } from "../features/data-status/api";
import { runBacktest } from "../features/backtest/api";
import { complianceAction, loadAudit, loadCompliance, loadRisk } from "../features/governance/api";
import { loadBondCandidates, loadBondDashboard, loadBondDiagnosis } from "../features/convertible-bonds/api";
import { createNewsCorrection, loadNewsIntelligence, syncNews } from "../features/news-intelligence/api";
import { createBackup, loadOperationsStatus, runManualJob, setSchedulerPaused, verifyBackup } from "../features/operations/api";
import { loadAShareCandidates, loadAShareDiagnosis } from "../features/a-shares/api";
import { loadCurrentDecision, loadDecisionDate } from "../features/decision-workbench/api";
import { SelectedInstrumentProvider } from "../features/instrument-selection/SelectedInstrumentProvider";
import { loadStockCockpit, prepareStockData, searchAShareInstruments } from "../features/stock-cockpit/api";
import { deleteAISettings, loadAISettings, saveAISettings } from "../features/data-settings/api";

export function App() {
  return <SelectedInstrumentProvider><Dashboard
    loadSnapshot={loadSnapshot}
    syncHistory={syncHistory}
    runBacktest={runBacktest}
    loadRisk={loadRisk} loadCompliance={loadCompliance} loadAudit={loadAudit} complianceAction={complianceAction}
    loadBondDashboard={loadBondDashboard} loadBondDiagnosis={loadBondDiagnosis} loadBondCandidates={loadBondCandidates}
    loadNewsIntelligence={loadNewsIntelligence} syncNews={syncNews} createNewsCorrection={createNewsCorrection}
    loadOperationsStatus={loadOperationsStatus} setSchedulerPaused={setSchedulerPaused} createBackup={createBackup} verifyBackup={verifyBackup} runManualJob={runManualJob}
    loadAShareCandidates={loadAShareCandidates} loadAShareDiagnosis={loadAShareDiagnosis}
    searchAShareInstruments={searchAShareInstruments}
    loadStockCockpit={loadStockCockpit}
    prepareStockData={prepareStockData}
    loadAISettings={loadAISettings} saveAISettings={saveAISettings} deleteAISettings={deleteAISettings}
    loadDecisionCurrent={loadCurrentDecision} loadDecisionDate={loadDecisionDate}
  /></SelectedInstrumentProvider>;
}
