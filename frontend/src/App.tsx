import { useState } from "react";
import { Shell, type Page } from "./components/Shell";
import { usePlanner } from "./hooks/usePlanner";
import { Dashboard } from "./pages/Dashboard";
import { Journal } from "./pages/Journal";
import { Planning } from "./pages/Planning";

export function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const planner = usePlanner();

  return (
    <Shell page={page} onPageChange={setPage} planner={planner}>
      {page === "dashboard" ? <Dashboard planner={planner} /> : null}
      {page === "planning" ? <Planning planner={planner} /> : null}
      {page === "analytics" ? (
        <Journal
          planner={planner}
          onOpenComparison={async (oldPlanId, newPlanId) => {
            await planner.comparePlans(oldPlanId, newPlanId);
            setPage("planning");
          }}
        />
      ) : null}
    </Shell>
  );
}
