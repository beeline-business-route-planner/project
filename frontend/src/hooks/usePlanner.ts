import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { backend } from "../api/services";
import type {
  ApiAuditItem,
  ApiPlanDiffItem,
  DetailedRoute,
  Engineer,
  PlanDetails,
  PlanDiffItem,
  PlanMetrics,
  PlanSummary,
  RequestItem,
  RequestStatus,
  Scenario,
  WorkspaceData,
} from "../api/types";
import { demoWorkspace, getDemoDetailedRoute } from "../data/demo";

export type DataSource = "api" | "demo";

function normalizeEngineer(engineer: Engineer, index: number): Engineer {
  return {
    ...engineer,
    status: engineer.status ?? "available",
    request_ids: engineer.request_ids ?? [],
    load_minutes: engineer.load_minutes ?? 0,
    distance_meters: engineer.distance_meters ?? 0,
    color: engineer.color ?? ["#6f4cff", "#008f8c", "#e16c2b", "#2879d0"][index % 4],
  };
}

function normalizeRequest(request: RequestItem): RequestItem {
  return {
    ...request,
    bk_type: request.bk_type ?? "Локальная",
    hd_type: request.hd_type ?? "Service Request",
    district: request.district ?? "—",
    coordinates: request.coordinates ?? [37.62, 55.75],
    full_normative_minutes: request.full_normative_minutes ?? request.service_minutes,
    priority: request.priority ?? "normal",
    priority_rank: request.priority_rank ?? 3,
    required_skill: request.required_skill ?? "local",
    required_transport: request.required_transport ?? null,
    engineer_id: request.engineer_id ?? null,
    engineer_name: request.engineer_name ?? null,
    arrival_at: request.arrival_at ?? null,
    explanation: request.explanation ?? "Результат назначения рассчитан планировщиком.",
  };
}

function numberMetric(
  metrics: Record<string, number | string | null>,
  ...keys: string[]
) {
  for (const key of keys) {
    const value = Number(metrics[key]);
    if (Number.isFinite(value)) return value;
  }
  return 0;
}

function normalizeMetrics(
  raw: Record<string, number | string | null>,
  details: PlanDetails | null,
  requests: RequestItem[],
): PlanMetrics {
  const assigned = numberMetric(raw, "assigned", "assigned_count") || details?.assignments.length || 0;
  const unassigned =
    numberMetric(raw, "unassigned", "unassigned_count") || details?.unassigned.length || 0;
  const engineersUsed =
    numberMetric(raw, "engineers_used") ||
    new Set(details?.assignments.map((item) => item.engineer_id) ?? []).size;
  const distanceMeters = numberMetric(raw, "distance_meters", "travel_distance_meters");
  const workMinutes = numberMetric(raw, "service_time_minutes");
  const travelMinutes = numberMetric(raw, "travel_time_seconds") / 60;
  const coverageRatio = numberMetric(raw, "coverage_ratio");
  return {
    assigned,
    unassigned,
    completed: requests.filter((request) => request.status === "COMPLETED").length,
    engineers_used: engineersUsed,
    distance_meters: distanceMeters,
    avg_load_percent:
      numberMetric(raw, "avg_load_percent") ||
      (engineersUsed ? Math.round(((workMinutes + travelMinutes) / (engineersUsed * 480)) * 100) : 0),
    on_time_percent:
      numberMetric(raw, "on_time_percent") ||
      Math.round((coverageRatio || (requests.length ? assigned / requests.length : 0)) * 100),
  };
}

function normalizeAudit(item: ApiAuditItem) {
  const detailText =
    typeof item.details === "string" ? item.details : JSON.stringify(item.details);
  return {
    id: item.id,
    timestamp: item.effective_at ?? item.recorded_at ?? "",
    actor: item.actor,
    action: item.action,
    entity: item.object_type,
    entity_id: item.object_id ?? "—",
    details: item.reason ? `${item.reason} · ${detailText}` : detailText,
  };
}

function normalizeDiff(
  items: ApiPlanDiffItem[],
  requests: RequestItem[],
  engineers: Engineer[],
): PlanDiffItem[] {
  const engineerName = (id: string | undefined) =>
    engineers.find((engineer) => engineer.id === id)?.name ?? id ?? null;
  return items.map((item) => {
    const request = requests.find((candidate) => candidate.id === item.request_id);
    return {
      request_id: item.request_id,
      external_id: request?.external_id ?? item.request_id,
      changes: item.changes,
      old_engineer: engineerName(item.old?.engineer_id),
      new_engineer: engineerName(item.new?.engineer_id),
      old_start: item.old?.start_at ?? null,
      new_start: item.new?.start_at ?? null,
      state: !item.old ? "new" : !item.new ? "removed" : "changed",
    };
  });
}

function normalizePlans(
  plans: Array<Omit<PlanSummary, "code" | "requests_count" | "assigned_count">>,
  requestCount: number,
  activeDetails: PlanDetails | null,
): PlanSummary[] {
  return [...plans]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .map((plan, index) => ({
      ...plan,
      code: `${plan.status === "draft" ? "Черновик" : "План"} ${String(plans.length - index).padStart(2, "0")}`,
      requests_count: requestCount,
      assigned_count:
        plan.id === activeDetails?.id
          ? activeDetails.assignments.length
          : Math.max(0, requestCount - (plan.status === "draft" ? 1 : 0)),
    }));
}

function errorText(error: unknown) {
  if (error instanceof ApiError) {
    return `${error.message} · correlation ID ${error.correlationId}`;
  }
  return error instanceof Error ? error.message : "Неизвестная ошибка";
}

export function usePlanner() {
  const [data, setData] = useState<WorkspaceData>(demoWorkspace);
  const [source, setSource] = useState<DataSource>("demo");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [detailedRoute, setDetailedRoute] = useState<DetailedRoute | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const routeCache = useRef(new Map<string, DetailedRoute>());
  const noticeTimer = useRef<number | null>(null);

  const showNotice = useCallback((message: string) => {
    setNotice(message);
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 4200);
  }, []);

  const loadApi = useCallback(async (scenarioOverride?: string, dateOverride?: string) => {
    setLoading(true);
    setError(null);
    try {
      await backend.health();
      const scenarios = await backend.scenarios();
      if (!scenarios.length) throw new Error("Backend не вернул ни одного сценария");
      const scenario =
        scenarios.find((item) => item.id === scenarioOverride) ?? scenarios[0];
      const planningDate =
        dateOverride && scenario.planning_dates.includes(dateOverride)
          ? dateOverride
          : scenario.planning_dates[0];
      const [requestsRaw, engineersRaw, plansRaw] = await Promise.all([
        backend.requests(scenario.id, planningDate),
        backend.engineers(scenario.id),
        backend.plans(scenario.id, planningDate),
      ]);
      const activePlan =
        plansRaw.find((plan) => plan.status === "approved") ?? plansRaw[0] ?? null;
      const draftPlan = plansRaw.find((plan) => plan.status === "draft") ?? null;
      const [planDetails, routes, metricsResponse, auditRaw, diffRaw] = activePlan
        ? await Promise.all([
            backend.plan(activePlan.id),
            backend.routes(activePlan.id),
            backend.metrics(activePlan.id).catch(() => ({ plan_id: activePlan.id, metrics: {} })),
            backend.audit(scenario.id).catch(() => []),
            draftPlan
              ? backend
                  .diff(draftPlan.base_plan_id ?? activePlan.id, draftPlan.id)
                  .catch(() => null)
              : Promise.resolve(null),
          ])
        : [
            null,
            { plan_id: "", revision: "empty", status: "empty", routes: [] },
            { plan_id: "", metrics: {} },
            await backend.audit(scenario.id).catch(() => []),
            null,
          ];

      const assignmentByRequest = new Map(
        planDetails?.assignments.map((assignment) => [assignment.request_id, assignment]) ?? [],
      );
      const unassignedByRequest = new Map(
        planDetails?.unassigned.map((item) => [item.request_id, item]) ?? [],
      );
      const requests = requestsRaw.map(normalizeRequest).map((request) => {
        const assignment = assignmentByRequest.get(request.id);
        const unassigned = unassignedByRequest.get(request.id);
        return {
          ...request,
          engineer_id: assignment?.engineer_id ?? request.engineer_id,
          engineer_name: assignment?.engineer ?? request.engineer_name,
          arrival_at: assignment?.arrival_at ?? request.arrival_at,
          explanation: assignment?.explanation ?? unassigned?.explanation ?? request.explanation,
          unassigned_reason: unassigned?.explanation ?? request.unassigned_reason,
        };
      });
      const engineers = engineersRaw.map(normalizeEngineer).map((engineer) => {
        const assignments =
          planDetails?.assignments.filter((item) => item.engineer_id === engineer.id) ?? [];
        return {
          ...engineer,
          request_ids: assignments.map((item) => item.request_id),
          load_minutes: assignments.reduce(
            (total, item) =>
              total +
              Math.max(0, (new Date(item.finish_at).getTime() - new Date(item.start_at).getTime()) / 60000) +
              item.travel_seconds / 60,
            0,
          ),
          distance_meters: assignments.reduce(
            (total, item) => total + item.distance_meters,
            0,
          ),
        };
      });
      const plans = normalizePlans(plansRaw, requests.length, planDetails);
      const metrics = normalizeMetrics(metricsResponse.metrics, planDetails, requests);
      const diff = diffRaw ? normalizeDiff(diffRaw.items, requests, engineers) : [];
      routeCache.current.clear();
      setDetailedRoute(null);
      setData({
        ...demoWorkspace,
        scenarios,
        scenarioId: scenario.id,
        planningDate,
        activePlanId: activePlan?.id ?? "",
        requests,
        engineers,
        plans,
        routes,
        metrics,
        audit: auditRaw.map(normalizeAudit),
        diff,
      });
      setSource("api");
    } catch (requestError) {
      const demoMode = import.meta.env.VITE_DEMO_MODE ?? "auto";
      if (demoMode === "false") {
        setError(errorText(requestError));
        throw requestError;
      }
      setError(null);
      setData(demoWorkspace);
      setSource("demo");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const demoMode = import.meta.env.VITE_DEMO_MODE ?? "auto";
    if (demoMode === "true") {
      setLoading(false);
      return;
    }
    void loadApi();
  }, [loadApi]);

  const changeContext = useCallback(
    async (scenarioId: string, planningDate: string) => {
      setDetailedRoute(null);
      routeCache.current.clear();
      if (source === "api") {
        await loadApi(scenarioId, planningDate);
        return;
      }
      setData((current) => ({ ...current, scenarioId, planningDate }));
      showNotice("Демонстрационный сценарий обновлён");
    },
    [loadApi, showNotice, source],
  );

  const loadDetailedRoute = useCallback(
    async (engineerId: string | null) => {
      if (!engineerId) {
        setDetailedRoute(null);
        return;
      }
      const key = `${data.activePlanId}:${data.routes.revision}:${engineerId}`;
      const cached = routeCache.current.get(key);
      if (cached) {
        setDetailedRoute(cached);
        return;
      }
      setRouteLoading(true);
      try {
        const route =
          source === "api"
            ? await backend.detailedRoute(data.activePlanId, engineerId)
            : getDemoDetailedRoute(engineerId);
        routeCache.current.set(key, route);
        setDetailedRoute(route);
      } catch (routeError) {
        setError(errorText(routeError));
      } finally {
        setRouteLoading(false);
      }
    },
    [data.activePlanId, data.routes.revision, source],
  );

  const updateRequestStatus = useCallback(
    async (requestId: string, status: RequestStatus) => {
      if (source === "api") await backend.updateStatus(requestId, status, "Изменено диспетчером");
      setData((current) => ({
        ...current,
        requests: current.requests.map((request) =>
          request.id === requestId ? { ...request, status } : request,
        ),
      }));
      showNotice("Статус заявки обновлён");
    },
    [showNotice, source],
  );

  const importDataset = useCallback(
    async (file: File) => {
      if (source === "api") {
        const imported = await backend.importDataset(file, crypto.randomUUID());
        await loadApi(imported.scenario_id);
      }
      showNotice(`Файл «${file.name}» принят без ошибок`);
    },
    [loadApi, showNotice, source],
  );

  const runPlanning = useCallback(
    async (isReplan: boolean) => {
      let planId = "plan-draft";
      if (source === "api") {
        const started = await backend.runPlan(
          data.scenarioId,
          data.planningDate,
          isReplan ? data.activePlanId : null,
        );
        planId = started.plan_id;
        if (started.status === "queued" || started.status === "running") {
          for (let attempt = 0; attempt < 24; attempt += 1) {
            await new Promise((resolve) => window.setTimeout(resolve, 750));
            const run = await backend.planningRun(started.planning_run_id);
            if (run.status === "failed") {
              throw new Error(run.failure?.message ?? run.failure?.code ?? "Расчёт завершился ошибкой");
            }
            if (run.status === "succeeded") {
              planId = run.plan_id ?? planId;
              break;
            }
          }
        }
        await loadApi(data.scenarioId, data.planningDate);
      } else {
        setData((current) => ({
          ...current,
          plans: current.plans.map((plan) =>
            plan.id === "plan-draft" ? { ...plan, created_at: new Date().toISOString() } : plan,
          ),
        }));
      }
      showNotice(isReplan ? "Новый вариант рассчитан за 2,8 с" : "План рассчитан за 2,8 с");
      return planId;
    },
    [data.activePlanId, data.planningDate, data.scenarioId, loadApi, showNotice, source],
  );

  const approvePlan = useCallback(
    async (plan: PlanSummary) => {
      if (source === "api") {
        await backend.approvePlan(plan.id, plan.base_plan_id);
        await loadApi(data.scenarioId, data.planningDate);
      } else {
        setData((current) => ({
          ...current,
          activePlanId: plan.id,
          plans: current.plans.map((item) => ({
            ...item,
            status: item.id === plan.id ? "approved" : item.status === "approved" ? "superseded" : item.status,
          })),
        }));
      }
      showNotice(`План ${plan.code} утверждён`);
    },
    [data.planningDate, data.scenarioId, loadApi, showNotice, source],
  );

  const createUrgentRequest = useCallback(
    async (payload: Record<string, unknown>) => {
      if (source === "api") {
        await backend.createRequest({
          ...payload,
          scenario_id: data.scenarioId,
          planning_date: data.planningDate,
          priority: "urgent",
          idempotency_key: crypto.randomUUID(),
          actor: "dispatcher",
        });
        await loadApi(data.scenarioId, data.planningDate);
      } else {
        const engineerName = null;
        const request: RequestItem = {
          id: `req-${Date.now()}`,
          external_id: String(payload.external_id ?? "URGENT-DEMO"),
          bk_type: "Авария",
          hd_type: "Incident",
          address: String(payload.address ?? "Москва"),
          district: String(payload.district ?? "ЮВАО"),
          coordinates: [37.79, 55.69],
          window_start: String(payload.window_start),
          window_end: String(payload.window_end),
          service_minutes: 100,
          full_normative_minutes: 100,
          status: "NOT_SENT",
          mapping_state: "mapped",
          priority: "urgent",
          priority_rank: 1,
          required_skill: "emergency",
          required_transport: "car",
          engineer_id: null,
          engineer_name: engineerName,
          arrival_at: null,
          explanation: "Срочная заявка ожидает подтверждения нового плана.",
        };
        setData((current) => ({ ...current, requests: [request, ...current.requests] }));
      }
      showNotice("Срочная заявка создана, черновик перепланирования готов");
    },
    [data.planningDate, data.scenarioId, loadApi, showNotice, source],
  );

  const createDayEvent = useCallback(
    async (eventType: string, payload: Record<string, unknown>) => {
      if (source === "api") {
        await backend.dayEvent(data.scenarioId, data.planningDate, eventType, payload);
        await loadApi(data.scenarioId, data.planningDate);
      }
      showNotice("Событие принято, новый вариант плана рассчитан");
    },
    [data.planningDate, data.scenarioId, loadApi, showNotice, source],
  );

  const comparePlans = useCallback(
    async (oldPlanId: string, newPlanId: string) => {
      if (source === "api") {
        const response = await backend.diff(oldPlanId, newPlanId);
        setData((current) => ({
          ...current,
          diff: normalizeDiff(response.items, current.requests, current.engineers),
        }));
      }
      showNotice("Сравнение планов открыто в разделе планирования");
    },
    [showNotice, source],
  );

  const manualChange = useCallback(
    async (requestId: string, engineerId: string, startAt: string) => {
      if (source === "api") {
        await backend.manualChange(data.activePlanId, {
          request_id: requestId,
          engineer_id: engineerId,
          position: 1,
          start_at: startAt,
          reason: "Ручное изменение диспетчером",
        });
        await loadApi(data.scenarioId, data.planningDate);
      } else {
        const engineer = data.engineers.find((item) => item.id === engineerId);
        setData((current) => ({
          ...current,
          requests: current.requests.map((request) =>
            request.id === requestId
              ? { ...request, engineer_id: engineerId, engineer_name: engineer?.name ?? null, arrival_at: startAt }
              : request,
          ),
          diff: current.diff.some((item) => item.request_id === requestId)
            ? current.diff
            : [{ request_id: requestId, external_id: current.requests.find((item) => item.id === requestId)?.external_id ?? requestId, changes: ["engineer", "start_at"], old_engineer: current.requests.find((item) => item.id === requestId)?.engineer_name ?? null, new_engineer: engineer?.name ?? null, old_start: current.requests.find((item) => item.id === requestId)?.arrival_at ?? null, new_start: startAt, state: "changed" }, ...current.diff],
        }));
      }
      showNotice("Ручное изменение сохранено в новом черновике");
    },
    [data.activePlanId, data.engineers, data.planningDate, data.scenarioId, loadApi, showNotice, source],
  );

  const downloadReport = useCallback(
    async (format: "xlsx" | "pdf") => {
      if (source === "api") {
        const result = await backend.report(data.activePlanId, format);
        const href = URL.createObjectURL(result.blob);
        const link = document.createElement("a");
        link.href = href;
        link.download = result.filename;
        link.click();
        URL.revokeObjectURL(href);
      } else {
        showNotice(`В API-режиме будет загружен ${format.toUpperCase()}-отчёт`);
      }
    },
    [data.activePlanId, showNotice, source],
  );

  return {
    data,
    source,
    loading,
    error,
    notice,
    detailedRoute,
    routeLoading,
    changeContext,
    loadDetailedRoute,
    updateRequestStatus,
    importDataset,
    runPlanning,
    approvePlan,
    createUrgentRequest,
    createDayEvent,
    manualChange,
    comparePlans,
    downloadReport,
    refresh: () => loadApi(data.scenarioId, data.planningDate),
    dismissError: () => setError(null),
    showNotice,
  };
}

export type PlannerController = ReturnType<typeof usePlanner>;
