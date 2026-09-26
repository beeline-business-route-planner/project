import { apiRequest } from "./client";
import type {
  BackendEngineerDetail,
  BackendInitialPlanningResponse,
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
  importInitial: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return apiRequest<BackendInitialPlanningResponse>("/planning/initial", {
      method: "POST",
      rawBody: form,
    });
  },
};
