import { apiRequest } from "./client";
import type {
  BackendEngineerDetail,
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
  engineer: (engineerId: string) =>
    apiRequest<BackendEngineerDetail>(`/engineers/${engineerId}`),
  request: (requestId: string) =>
    apiRequest<BackendRequestDetail>(`/requests/${requestId}`),
  importInitial: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return apiRequest<{
      status: string;
      imports: Array<{
        upload_id: string;
        region: BackendRegion;
        requests_count: number;
        engineers_count: number;
        plan_id: string | null;
      }>;
    }>("/planning/initial", { method: "POST", rawBody: form });
  },
};
