import { Dashboard } from "../features/dashboard/Dashboard";
import { loadSnapshot } from "../features/dashboard/api";
import { syncHistory } from "../features/data-status/api";

export function App() {
  return <Dashboard loadSnapshot={loadSnapshot} syncHistory={syncHistory} />;
}
