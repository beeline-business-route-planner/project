import { ApiError, apiBlob, apiRequest } from "./client";
import type {
  ApiAuditItem,
  ApiPlanDiffItem,
  DetailedRoute,
  Engineer,
  OverviewRoutesResponse,
  PlanDetails,
  PlanningRun,
  PlanSummary,
  RequestItem,
  RequestStatus,
  Scenario,
  StoredPlanRoute,
} from "./types";

function query(params: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) search.set(key, String(value));
  });
  return search.toString();
}

export const backend = {
  health: () => apiRequest<{ status: string }>("/health"),
  scenarios: () => apiRequest<Scenario[]>("/scenarios"),
  requests: (scenarioId: string, planningDate: string) =>
    apiRequest<RequestItem[]>(
      `/requests?${query({ scenario_id: scenarioId, planning_date: planningDate, limit: 100, offset: 0 })}`,
    ),
  engineers: (scenarioId: string) =>
    apiRequest<Engineer[]>(`/engineers?${query({ scenario_id: scenarioId })}`),
  plans: (scenarioId: string, planningDate: string) =>
    apiRequest<Array<Omit<PlanSummary, "code" | "requests_count" | "assigned_count">>>(
      `/plans?${query({ scenario_id: scenarioId, planning_date: planningDate })}`,
    ),
  plan: (planId: string) => apiRequest<PlanDetails>(`/plans/${planId}`),
  routes: async (planId: string) => {
    try {
      return await apiRequest<OverviewRoutesResponse>(`/plans/${planId}/routes`);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      const plan = await apiRequest<PlanDetails>(`/plans/${planId}`);
      return overviewFromStoredPlan(plan);
    }
  },
  detailedRoute: async (planId: string, engineerId: string) => {
    try {
      return await apiRequest<DetailedRoute>(
        `/plans/${planId}/engineers/${engineerId}/route`,
      );
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      const legacy = await apiRequest<{
        plan_id: string;
        engineer_id: string;
        stops: PlanDetails["assignments"];
        route: StoredPlanRoute | null;
      }>(`/engineers/${engineerId}/route?${query({ plan_id: planId })}`);
      return detailedFromLegacy(legacy);
    }
  },
  metrics: (planId: string) =>
    apiRequest<{
      plan_id: string;
      metrics: Record<string, number | string | null>;
      unassigned?: PlanDetails["unassigned"];
    }>(`/plans/${planId}/metrics`),
  audit: (scenarioId: string) =>
    apiRequest<ApiAuditItem[]>(
      `/audit?${query({ scenario_id: scenarioId, limit: 100, offset: 0 })}`,
    ),
  diff: (oldPlanId: string, newPlanId: string) =>
    apiRequest<{
      old_plan_id: string;
      new_plan_id: string;
      summary: Record<string, number>;
      items: ApiPlanDiffItem[];
    }>(
      `/plans/diff?${query({ old_plan_id: oldPlanId, new_plan_id: newPlanId })}`,
    ),
  importDataset: (file: File, idempotencyKey: string) => {
    const form = new FormData();
    form.append("file", file);
    return apiRequest<{ dataset_id: string; scenario_id: string; duplicate: boolean }>("/imports", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      rawBody: form,
    });
  },
  runPlan: (scenarioId: string, planningDate: string, basePlanId: string | null) =>
    apiRequest<{ planning_run_id: string; plan_id: string; status: string }>("/plans/run", {
      method: "POST",
      body: {
        scenario_id: scenarioId,
        planning_date: planningDate,
        base_plan_id: basePlanId,
        as_of: null,
      },
    }),
  planningRun: (planningRunId: string) =>
    apiRequest<PlanningRun>(`/planning-runs/${planningRunId}`),
  approvePlan: (planId: string, expectedBasePlanId: string | null) =>
    apiRequest<{ plan_id: string; status: string }>(`/plans/${planId}/approve`, {
      method: "POST",
      body: { expected_base_plan_id: expectedBasePlanId, actor: "dispatcher" },
    }),
  manualChange: (planId: string, payload: Record<string, unknown>) =>
    apiRequest<{ plan_id: string; status: string; parent_plan_id: string }>(
      `/plans/${planId}/manual-change`,
      { method: "POST", body: { ...payload, actor: "dispatcher" } },
    ),
  updateStatus: (requestId: string, status: RequestStatus, reason: string) =>
    apiRequest(`/requests/${requestId}/facts`, {
      method: "POST",
      body: {
        status,
        effective_at: new Date().toISOString(),
        actor: "dispatcher",
        reason,
        actual_start: status === "IN_PROGRESS" ? new Date().toISOString() : null,
        actual_finish: status === "COMPLETED" ? new Date().toISOString() : null,
      },
    }),
  createRequest: (payload: Record<string, unknown>) =>
    apiRequest<{ request_id: string; event_id: string; duplicate: boolean; replanning?: { plan_id: string } }>(
      "/requests",
      { method: "POST", body: payload },
    ),
  dayEvent: (
    scenarioId: string,
    planningDate: string,
    eventType: string,
    payload: Record<string, unknown>,
  ) =>
    apiRequest("/events", {
      method: "POST",
      body: {
        scenario_id: scenarioId,
        planning_date: planningDate,
        event_type: eventType,
        effective_at: new Date().toISOString(),
        payload,
        idempotency_key: crypto.randomUUID(),
        actor: "dispatcher",
      },
    }),
  report: (planId: string, format: "xlsx" | "pdf") =>
    apiBlob(`/plans/${planId}/reports/${format}`),
};

function overviewFromStoredPlan(plan: PlanDetails): OverviewRoutesResponse {
  return {
    plan_id: plan.id,
    revision: plan.input_version || plan.id,
    status: plan.status,
    routes: plan.routes.map((route) => {
      const assignments = plan.assignments.filter(
        (assignment) => assignment.engineer_id === route.engineer_id,
      );
      return {
        engineer_id: route.engineer_id,
        profile: route.profile,
        route_status: route.geometry ? "ready" : "empty",
        provider: route.provider ?? route.geometry?.provider ?? "stored",
        graph_fingerprint: route.graph_fingerprint ?? plan.input_version ?? plan.id,
        geometry: route.geometry,
        distance_meters:
          route.distance_meters ??
          assignments.reduce((total, assignment) => total + assignment.distance_meters, 0),
        duration_seconds:
          route.duration_seconds ??
          assignments.reduce((total, assignment) => total + assignment.travel_seconds, 0),
      };
    }),
  };
}

function detailedFromLegacy(legacy: {
  plan_id: string;
  engineer_id: string;
  stops: PlanDetails["assignments"];
  route: StoredPlanRoute | null;
}): DetailedRoute {
  const route = legacy.route;
  return {
    plan_id: legacy.plan_id,
    revision: legacy.plan_id,
    status: "stored",
    engineer_id: legacy.engineer_id,
    profile: route?.profile ?? "driving",
    route_status: route?.geometry ? "ready" : "empty",
    provider: route?.provider ?? route?.geometry?.provider ?? "stored",
    graph_fingerprint: route?.graph_fingerprint ?? legacy.plan_id,
    geometry: route?.geometry ?? null,
    distance_meters:
      route?.distance_meters ??
      legacy.stops.reduce((total, stop) => total + stop.distance_meters, 0),
    duration_seconds:
      route?.duration_seconds ??
      legacy.stops.reduce((total, stop) => total + stop.travel_seconds, 0),
    stops: [],
    segments: [],
  };
}
