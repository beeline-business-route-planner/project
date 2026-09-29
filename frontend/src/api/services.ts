import { apiRequest } from "./client";
import type {
  BackendEngineerDetail,
  BackendEventResult,
  BackendExport,
  BackendInitialPlanningResponse,
  BackendPlanningEvent,
  BackendPlanningResult,
  BackendPlanDetail,
  BackendPlanSummary,
  BackendRegion,
  BackendRequestDetail,
} from "./types";

function query(params: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) search.set(key, String(value));
  });
  return search.toString();
}

export const backend = {
  ping: () => apiRequest<{ ping: string }>("/ping", { signal: AbortSignal.timeout(5000) }),
  plans: (region: BackendRegion) =>
    apiRequest<BackendPlanSummary[]>(`/plans?${query({ region })}`),
  currentPlan: (region: BackendRegion, planningDate?: string) =>
    apiRequest<BackendPlanDetail>(
      `/plans/current?${query({ region, planning_date: planningDate })}`,
    ),
  plan: (planId: string) => apiRequest<BackendPlanDetail>(`/plans/${planId}`),
  approvePlan: (planId: string) =>
    apiRequest<BackendPlanSummary>(`/plans/${planId}/approve`, { method: "POST" }),
  rejectPlan: (planId: string) =>
    apiRequest<BackendPlanSummary>(`/plans/${planId}/reject`, { method: "POST" }),
  engineer: (engineerId: string) =>
    apiRequest<BackendEngineerDetail>(`/engineers/${engineerId}`),
  request: (requestId: string) =>
    apiRequest<BackendRequestDetail>(`/requests/${requestId}`),
  updateRequestStatus: (requestId: string, status: string) =>
    apiRequest<BackendRequestDetail>(`/requests/${requestId}/status`, { method: "PATCH", body: { status } }),
  importInitial: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return apiRequest<BackendInitialPlanningResponse>("/planning/initial", {
      method: "POST",
      rawBody: form,
    });
  },
  replan: (regions: BackendRegion[]) => apiRequest<BackendPlanningResult>("/planning/replan", { method: "POST", body: { regions } }),
  event: (payload: BackendPlanningEvent) => apiRequest<BackendEventResult>("/planning/events", { method: "POST", body: payload }),
  exportPlan: (planId: string) => apiRequest<BackendExport>(`/plans/${planId}/export`),
  exportDailyReport: (planningDate: string) => apiRequest<BackendExport>(`/reports/daily?${query({ planning_date: planningDate })}`),
};
