import { useState } from "react";
import { Shell, type Page } from "./components/Shell";
import { usePlanner } from "./hooks/usePlanner";
import { Dashboard } from "./pages/Dashboard";
import { Journal } from "./pages/Journal";
import { Planning } from "./pages/Planning";

export function App() {
  const [page, setPage] = useState<Page>("dashboard");
  // A request to open on the dashboard map when another page links to it.
  const [focusRequestId, setFocusRequestId] = useState<string | null>(null);
  const planner = usePlanner();
  const changePage = (next: Page) => {
    setFocusRequestId(null);
    setPage(next);
  };
  const openRequestOnMap = (requestId: string) => {
    setFocusRequestId(requestId);
    setPage("dashboard");
  };

  return (
    <Shell page={page} onPageChange={changePage} planner={planner}>
      {page === "dashboard" ? <Dashboard planner={planner} focusRequestId={focusRequestId} /> : null}
      {page === "planning" ? <Planning planner={planner} onOpenRequest={openRequestOnMap} /> : null}
      {page === "analytics" ? <Journal planner={planner} onOpenRequest={openRequestOnMap} /> : null}
    </Shell>
  );
}
