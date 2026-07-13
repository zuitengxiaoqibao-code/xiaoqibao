import { Dashboard } from "../features/dashboard/Dashboard";
import { loadSnapshot } from "../features/dashboard/api";

export function App() {
  return <Dashboard loadSnapshot={loadSnapshot} />;
}

