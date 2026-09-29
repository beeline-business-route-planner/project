import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { backend } from "../api/services";
import type {
  BackendEngineerDetail,
  BackendEngineerTile,
  BackendEventType,
  BackendPlanningEvent,
  BackendUrgentRequest,
  BackendPlanDetail,
  BackendPlanSummary,
  BackendRegion,
  BackendRequestDetail,
  BackendRequestTile,
  DetailedRoute,
  Engineer,
  OverviewRoutesResponse,
  PlanDiffItem,
  PlanMetrics,
  PlanStatus,
  PlanSummary,
  RequestItem,
  RequestStatus,
  Scenario,
  Skill,
  Transport,
  WorkspaceData,
} from "../api/types";
import { demoWorkspace, getDemoDetailedRoute } from "../data/demo";

export type DataSource = "api" | "demo";

const apiScenarios: Scenario[] = [
  { id: "yugo_vostok", code: "yugo_vostok", name: "Юго-восток", timezone: "Europe/Moscow", planning_dates: [] },
  { id: "vostok", code: "vostok", name: "Восток", timezone: "Europe/Moscow", planning_dates: [] },
  { id: "yugotsentr", code: "yugotsentr", name: "Югоцентр", timezone: "Europe/Moscow", planning_dates: [] },
];

const colors = ["#ffd400", "#28c6b7", "#ff7a59", "#54a7ff", "#8ed35f", "#ffb84d"];

const skillMap: Record<string, Skill> = {
  local_works: "local",
  connection_and_orders: "connection",
  emergency_works: "emergency",
};

const vehicleMap: Record<string, Transport> = {
  car: "car",
  pedestrian: "walking",
  bicycle: "bicycle",
  public_transport: "transit",
};

const statusMap: Record<string, RequestStatus> = {
  not_sent: "NOT_SENT",
  sent: "SENT",
  on_the_way: "EN_ROUTE",
  in_progress: "IN_PROGRESS",
  done: "COMPLETED",
  cancelled: "CANCELLED",
  overdue: "OVERDUE",
};

const backendStatus: Record<Exclude<RequestStatus, "CANCELLED">, string> = {
  NOT_SENT: "not_sent",
  SENT: "sent",
  EN_ROUTE: "on_the_way",
  IN_PROGRESS: "in_progress",
  COMPLETED: "done",
  OVERDUE: "overdue",
};

const unassignedLabels: Record<string, string> = {
  no_matching_skill: "Нет инженера с нужной квалификацией",
  no_matching_vehicle: "Нет подходящего транспорта",
  no_time_slot: "Нет совместимого временного окна",
  no_route: "Нет маршрута до адреса",
  no_available_engineer: "Нет доступного инженера",
};

const workLabels: Record<string, string> = {
  local_works: "Локальные работы",
  connection_and_orders: "Подключение",
  emergency_works: "Авария",
};

const requestTypeLabels: Record<string, string> = {
  global_problem: "Авария",
  connection: "Подключение",
  additional_order: "Дозаказ",
  local_request: "Локальная",
};

function number(value: number | string | null | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function validPoint(longitude: number | string | null | undefined, latitude: number | string | null | undefined): [number, number] | null {
  if (longitude == null || latitude == null) return null;
  const lng = Number(longitude);
  const lat = Number(latitude);
  return Number.isFinite(lng) && Number.isFinite(lat) && Math.abs(lng) <= 180 && Math.abs(lat) <= 90 && (lng !== 0 || lat !== 0)
    ? [lng, lat] : null;
}

function orderedStops(engineer: BackendEngineerTile) {
  return [...engineer.stops].sort((left, right) =>
    (left.sequence_number ?? Number.MAX_SAFE_INTEGER) - (right.sequence_number ?? Number.MAX_SAFE_INTEGER));
}

function errorText(error: unknown) {
  if (error instanceof ApiError) return `${error.message} · HTTP ${error.status}`;
  return error instanceof Error ? error.message : "Неизвестная ошибка";
}

function regionOf(value?: string): BackendRegion {
  if (value === "vostok" || value === "yugotsentr" || value === "yugo_vostok") return value;
  if (value === "scenario-east") return "vostok";
  if (value === "scenario-south-center") return "yugotsentr";
  return "yugo_vostok";
}

function planStatus(plan: BackendPlanSummary): PlanStatus {
  if (plan.approval_status === "pending") return "draft";
  if (plan.approval_status === "rejected") return "rejected";
  return plan.is_current ? "approved" : "superseded";
}

function normalizePlans(plans: BackendPlanSummary[]): PlanSummary[] {
  return [...plans]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .map((plan, index) => ({
      id: plan.id,
      code: `PLN-${plan.planning_date.replaceAll("-", "").slice(2)}-${String(plans.length - index).padStart(2, "0")}`,
      status: planStatus(plan),
      parent_plan_id: plan.based_on_plan_id,
      base_plan_id: plan.based_on_plan_id,
      input_version: plan.id,
      created_at: plan.created_at,
      approved_at: plan.approved_at,
      requests_count: plan.assigned_requests_count + plan.unassigned_requests_count,
      assigned_count: plan.assigned_requests_count,
      distance_meters: number(plan.total_mileage_km) * 1000,
    }));
}

function normalizeMetrics(plan: BackendPlanDetail, requests: RequestItem[]): PlanMetrics {
  const raw = plan.metrics;
  const avg = number(raw.average_workload_with_travel);
  return {
    assigned: raw.assigned_requests_count,
    unassigned: raw.unassigned_requests_count,
    completed: requests.filter((request) => request.status === "COMPLETED").length,
    engineers_used: raw.engineers_used_count,
    distance_meters: number(raw.total_mileage_km) * 1000,
    avg_load_percent: Math.round(avg <= 1 ? avg * 100 : avg),
    coverage_percent: raw.assigned_requests_count + raw.unassigned_requests_count
      ? Math.round(raw.assigned_requests_count / (raw.assigned_requests_count + raw.unassigned_requests_count) * 100)
      : 0,
  };
}

function requestFromBackend(
  tile: BackendRequestTile,
  detail: BackendRequestDetail | null,
): RequestItem {
  const rank = Math.min(3, Math.max(1, detail?.priority ?? tile.priority)) as 1 | 2 | 3;
  const requiredSkill = detail?.required_skill ?? tile.required_skill;
  const reason = tile.unassigned_reason
    ? unassignedLabels[tile.unassigned_reason] ?? tile.unassigned_reason
    : undefined;
  const coordinates = validPoint(detail?.longitude ?? tile.longitude, detail?.latitude ?? tile.latitude);
  return {
    id: tile.request_id,
    external_id: `BK-${detail?.external_id ?? tile.external_id}`,
    bk_type: detail?.type_bk
      ? requestTypeLabels[detail.type_bk] ?? detail.type_bk
      : workLabels[requiredSkill] ?? requiredSkill,
    hd_type: detail?.type_hd ?? "Service request",
    address: detail?.address ?? tile.address,
    district: detail?.district ?? tile.district,
    coordinates: coordinates ?? [0, 0],
    window_start: detail?.window_start ?? tile.window_start,
    window_end: detail?.window_end ?? tile.window_end,
    service_minutes: detail?.norm_minutes_without_travel ?? 90,
    full_normative_minutes: detail?.norm_minutes ?? 90,
    status: detail?.status && detail.status !== "not_sent"
      ? statusMap[detail.status] ?? "NOT_SENT"
      : tile.assigned_engineer ? "SENT" : "NOT_SENT",
    mapping_state: coordinates ? "mapped" : "unmapped",
    priority: rank === 1 ? "urgent" : "normal",
    priority_rank: rank,
    required_skill: skillMap[requiredSkill] ?? "local",
    required_transport: detail?.required_vehicle_type
      ? vehicleMap[detail.required_vehicle_type] ?? null
      : null,
    engineer_id: tile.assigned_engineer?.engineer_id ?? null,
    engineer_name: tile.assigned_engineer?.name ?? null,
    arrival_at: tile.planned_arrival,
    explanation: tile.assigned_engineer
      ? "Назначение рассчитано актуальным backend с учётом квалификации, окна и загрузки."
      : reason ?? "Заявка пока не назначена.",
    unassigned_reason: reason,
  };
}

function engineerFromBackend(
  tile: BackendEngineerTile,
  detail: BackendEngineerDetail | null,
  index: number,
): Engineer {
  const load = number(tile.workload_with_travel);
  return {
    id: tile.engineer_id,
    external_code: `ENG-${tile.engineer_id.slice(0, 4).toUpperCase()}`,
    name: tile.name,
    transport: vehicleMap[detail?.vehicle_type ?? tile.vehicle_type] ?? "car",
    skills: (detail?.skills ?? []).map((skill) => skillMap[skill] ?? "local"),
    status: detail?.is_available === false ? "unavailable" : tile.assigned_requests_count ? "working" : "available",
    request_ids: orderedStops(tile).map((stop) => stop.request_id),
    load_minutes: Math.round(load <= 1 ? load * 480 : load * 4.8),
    distance_meters: number(tile.route_distance_km) * 1000,
    color: colors[index % colors.length],
  };
}

function routesFromPlan(plan: BackendPlanDetail): OverviewRoutesResponse {
  return {
    plan_id: plan.id,
    revision: plan.created_at,
    status: plan.approval_status,
    routes: plan.engineers.map((engineer) => {
      const routePoints = [
        validPoint(engineer.start_longitude, engineer.start_latitude),
        ...orderedStops(engineer).map((stop) => validPoint(stop.longitude, stop.latitude)),
      ].filter((point): point is [number, number] => point !== null);
      const coordinates = routePoints.filter((point, index) =>
        index === 0 || point[0] !== routePoints[index - 1][0] || point[1] !== routePoints[index - 1][1]);
      return {
        engineer_id: engineer.engineer_id,
        profile: engineer.vehicle_type,
        route_status: coordinates.length > 1 ? "ready" as const : "empty" as const,
        provider: "backend-plan",
        graph_fingerprint: plan.id,
        geometry: coordinates.length > 1 ? { type: "LineString" as const, coordinates } : null,
        distance_meters: number(engineer.route_distance_km) * 1000,
        duration_seconds: engineer.stops.reduce((sum, stop) => sum + (stop.travel_minutes ?? 0) * 60, 0),
      };
    }),
  };
}

function diffFromPlan(plan: BackendPlanDetail, engineers: Engineer[]): PlanDiffItem[] {
  const name = (id: string | null | undefined) =>
    engineers.find((engineer) => engineer.id === id)?.name ?? id ?? null;
  return (plan.diff?.requests ?? [])
    .filter((item) => !item.changes.includes("unchanged"))
    .map((item) => ({
      request_id: item.request_id,
      external_id: `BK-${item.after?.external_id ?? item.before?.external_id ?? item.request_id.slice(0, 6)}`,
      changes: item.changes,
      old_engineer: name(item.before?.engineer_id),
      new_engineer: name(item.after?.engineer_id),
      old_start: item.before?.planned_start ?? null,
      new_start: item.after?.planned_start ?? null,
      state: !item.before ? "new" : !item.after ? "removed" : "changed",
    }));
}

export function usePlanner() {
  const [data, setData] = useState<WorkspaceData>(demoWorkspace);
  const [source, setSource] = useState<DataSource>("demo");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [detailedRoute, setDetailedRoute] = useState<DetailedRoute | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const noticeTimer = useRef<number | null>(null);

  const showNotice = useCallback((message: string) => {
    setNotice(message);
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 4200);
  }, []);

  const loadApi = useCallback(async (scenarioOverride?: string, dateOverride?: string, planId?: string, strict = false) => {
    setLoading(true);
    setError(null);
    try {
      const region = regionOf(scenarioOverride);
      const summaries = await backend.plans(region);
      if (!summaries.length) throw new Error("Для выбранного участка пока нет рассчитанных планов");
      const availableDates = [...new Set(summaries.map((plan) => plan.planning_date))].sort().reverse();
      if (dateOverride && !availableDates.includes(dateOverride)) {
        throw new Error(`На ${dateOverride} для выбранного участка нет плана. Загрузите исходные XLSX в «Планировании».`);
      }
      // `is_current` identifies the active version, not necessarily today's
      // working day. Open the newest available day first, then its current plan.
      const planningDate = dateOverride || availableDates[0];
      const selectedSummary =
        summaries.find((plan) => plan.id === planId) ??
        summaries.find((plan) => plan.is_current && plan.planning_date === planningDate) ??
        summaries.find((plan) => plan.planning_date === planningDate) ??
        summaries[0];
      const plan = await backend.plan(selectedSummary.id);
      const tiles = [...new Map(
        plan.request_groups.flatMap((group) => group.requests).map((item) => [item.request_id, item]),
      ).values()];
      const [requestDetails, engineerDetails] = await Promise.all([
        Promise.all(tiles.map((tile) => backend.request(tile.request_id).catch(() => null))),
        Promise.all(plan.engineers.map((engineer) => backend.engineer(engineer.engineer_id).catch(() => null))),
      ]);
      const requests = tiles.map((tile, index) => requestFromBackend(tile, requestDetails[index]));
      const engineers = plan.engineers.map((engineer, index) =>
        engineerFromBackend(engineer, engineerDetails[index], index),
      );
      const plans = normalizePlans(summaries);
      const scenarios = apiScenarios.map((scenario) => ({
        ...scenario,
        planning_dates: scenario.id === region ? availableDates : [planningDate],
      }));
      setDetailedRoute(null);
      setData({
        scenarios,
        scenarioId: region,
        planningDate,
        activePlanId: plan.id,
        requests,
        engineers,
        plans,
        routes: routesFromPlan(plan),
        metrics: normalizeMetrics(plan, requests),
        audit: plans.map((item) => ({
          id: `audit-${item.id}`,
          timestamp: item.created_at,
          actor: "Система",
          action: item.status === "approved" ? "План утверждён" : "Версия плана создана",
          entity: "plan",
          entity_id: item.code,
          details: "Запись восстановлена из истории версий плана; отдельный журнал действий backend не предоставляет.",
        })),
        diff: diffFromPlan(plan, engineers),
      });
      setSource("api");
    } catch (requestError) {
      const demoMode = import.meta.env.VITE_DEMO_MODE ?? "auto";
      if (strict || demoMode === "false") {
        const message = errorText(requestError);
        setError(message);
        if (strict) throw requestError;
      } else {
        setError(`Показаны демонстрационные данные: ${errorText(requestError)}`);
        setData(demoWorkspace);
        setSource("demo");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if ((import.meta.env.VITE_DEMO_MODE ?? "auto") === "true") {
      setLoading(false);
      return;
    }
    void loadApi();
  }, [loadApi]);

  const apiUnavailable = useCallback((feature: string) => {
    showNotice(`${feature}: в текущем backend endpoint ещё не опубликован`);
  }, [showNotice]);

  const changeContext = useCallback(async (scenarioId: string, planningDate: string) => {
    setDetailedRoute(null);
    if (source === "api") {
      try { await loadApi(scenarioId, planningDate, undefined, true); }
      catch (error) { showNotice(errorText(error)); }
    }
    else {
      setData((current) => ({ ...current, scenarioId, planningDate }));
      showNotice("Демонстрационный сценарий обновлён");
    }
  }, [loadApi, showNotice, source]);

  const loadDetailedRoute = useCallback(async (engineerId: string | null) => {
    if (!engineerId) {
      setDetailedRoute(null);
      return;
    }
    setRouteLoading(true);
    try {
      if (source === "demo") {
        setDetailedRoute(getDemoDetailedRoute(engineerId));
        return;
      }
      const route = data.routes.routes.find((item) => item.engineer_id === engineerId);
      const stops = data.requests
        .filter((request) => request.engineer_id === engineerId)
        .sort((left, right) => (left.arrival_at ?? "").localeCompare(right.arrival_at ?? ""))
        .map((request, index) => ({
          sequence: index + 1,
          location_id: request.id,
          request_id: request.id,
          coordinates: request.coordinates,
          snapped_coordinates: request.coordinates,
        }));
      setDetailedRoute({
        plan_id: data.activePlanId,
        revision: data.routes.revision,
        status: data.routes.status,
        engineer_id: engineerId,
        profile: route?.profile ?? "driving",
        route_status: route?.route_status ?? "empty",
        provider: route?.provider ?? "backend-plan",
        graph_fingerprint: route?.graph_fingerprint ?? data.activePlanId,
        geometry: route?.geometry ?? null,
        distance_meters: route?.distance_meters ?? 0,
        duration_seconds: route?.duration_seconds ?? 0,
        stops,
        segments: [],
      });
    } finally {
      setRouteLoading(false);
    }
  }, [data, source]);

  const updateRequestStatus = useCallback(async (requestId: string, status: RequestStatus) => {
    if (source === "api") {
      if (status === "CANCELLED") throw new Error("Отмена заявки выполняется через «Новое событие» в планировании");
      await backend.updateRequestStatus(requestId, backendStatus[status]);
      await loadApi(data.scenarioId, data.planningDate, data.activePlanId, true);
      showNotice("Статус заявки обновлён");
      return;
    }
    if ((import.meta.env.VITE_DEMO_MODE ?? "auto") !== "true") throw new Error("Изменение статуса требует backend endpoint");
    setData((current) => ({
      ...current,
      requests: current.requests.map((request) => request.id === requestId ? { ...request, status } : request),
    }));
    showNotice("Статус заявки обновлён");
  }, [data.activePlanId, data.planningDate, data.scenarioId, loadApi, showNotice, source]);

  const importDataset = useCallback(async (files: File[]) => {
    if ((import.meta.env.VITE_DEMO_MODE ?? "auto") === "true") throw new Error("Импорт требует подключения backend");
    if (files.length !== 2) throw new Error("Выберите два Excel-файла одного округа: заявки и инженеры");
    const result = await backend.importInitial(files);
    const imported = result.regions.find((item) => item.status === "success" && item.plan_summary);
    if (!imported) {
      const reason = result.regions.find((item) => item.error)?.error?.detail;
      throw new Error(reason ?? "Backend не создал план ни для одного региона");
    }
    await loadApi(imported.region, imported.plan_summary?.planning_date, imported.plan_summary?.id, true);
    showNotice("Пара Excel-файлов принята, план рассчитан");
  }, [loadApi, showNotice]);

  const runPlanning = useCallback(async (isReplan: boolean) => {
    if (source === "api") {
      const region = regionOf(data.scenarioId);
      const result = await backend.replan([region]);
      const completed = result.regions.find((item) => item.region === region && item.status === "success" && item.plan_summary);
      if (!completed?.plan_summary) throw new Error(result.regions[0]?.error?.detail ?? "Backend не создал новый план");
      await loadApi(region, completed.plan_summary.planning_date, completed.plan_summary.id, true);
      showNotice("Новый вариант плана рассчитан");
      return completed.plan_summary.id;
    }
    if ((import.meta.env.VITE_DEMO_MODE ?? "auto") !== "true") throw new Error("Для расчёта подключите backend и загрузите исходные данные");
    showNotice(isReplan ? "Демонстрационный вариант рассчитан" : "Демонстрационный план рассчитан");
    return "plan-draft";
  }, [data.scenarioId, loadApi, showNotice, source]);

  const approvePlan = useCallback(async (plan: PlanSummary) => {
    if (source === "api") {
      await backend.approvePlan(plan.id);
      await loadApi(data.scenarioId, data.planningDate, plan.id, true);
      showNotice(`План ${plan.code} утверждён`);
      return;
    }
    if ((import.meta.env.VITE_DEMO_MODE ?? "auto") !== "true") throw new Error("Утверждение плана требует подключения backend");
    setData((current) => ({
      ...current,
      activePlanId: plan.id,
      plans: current.plans.map((item) => ({
        ...item,
        status: item.id === plan.id ? "approved" : item.status === "approved" ? "superseded" : item.status,
      })),
    }));
    showNotice(`План ${plan.code} утверждён`);
  }, [data.planningDate, data.scenarioId, loadApi, showNotice, source]);

  const rejectPlan = useCallback(async (plan: PlanSummary) => {
    if (source !== "api") throw new Error("Отклонение плана требует подключения backend");
    await backend.rejectPlan(plan.id);
    await loadApi(data.scenarioId, data.planningDate, undefined, true);
    showNotice(`План ${plan.code} отклонён`);
  }, [data.planningDate, data.scenarioId, loadApi, showNotice, source]);

  const createUrgentRequest = useCallback(async (payload: Record<string, unknown>) => {
    if (source === "api") {
      const isConnection = payload.type_bk === "connection";
      const urgent: BackendUrgentRequest = {
        external_id: Date.now(),
        type_bk: isConnection ? "connection" : "global_problem",
        type_hd: isConnection ? "connection_request" : "emergency",
        district: String(payload.district ?? ""),
        address: String(payload.address ?? ""),
        connection_type: null,
        is_gigabit: false,
        window_start: String(payload.window_start),
        window_end: String(payload.window_end),
        norm_minutes: isConnection ? 90 : 100,
        norm_minutes_without_travel: isConnection ? 70 : 80,
        priority: isConnection ? 2 : 1,
        required_skill: isConnection ? "connection_and_orders" : "emergency_works",
        required_vehicle_type: "car",
      };
      const result = await backend.event({ region: regionOf(data.scenarioId), event_type: "urgent_request", urgent_request: urgent });
      await loadApi(data.scenarioId, result.plan.planning_date, result.plan.id, true);
      showNotice("Срочная заявка создана, план пересчитан");
      return;
    }
    if ((import.meta.env.VITE_DEMO_MODE ?? "auto") !== "true") throw new Error("Создание заявки требует подключения backend");
    const request: RequestItem = {
      id: `req-${Date.now()}`,
      external_id: `BK-${Date.now()}`,
      bk_type: payload.type_bk === "connection" ? "Подключение" : "Авария",
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
      engineer_name: null,
      arrival_at: null,
      explanation: "Срочная заявка ожидает подтверждения нового плана.",
    };
    setData((current) => ({ ...current, requests: [request, ...current.requests] }));
    showNotice("Срочная заявка создана");
  }, [data.scenarioId, loadApi, showNotice, source]);

  const createDayEvent = useCallback(async (eventType: BackendEventType, payload: { engineer_id?: string; request_id?: string }) => {
    if (source === "api") {
      const event: BackendPlanningEvent = { region: regionOf(data.scenarioId), event_type: eventType, ...payload };
      const result = await backend.event(event);
      await loadApi(data.scenarioId, result.plan.planning_date, result.plan.id, true);
    } else if ((import.meta.env.VITE_DEMO_MODE ?? "auto") !== "true") {
      throw new Error("Событие рабочего дня требует подключения backend");
    }
    showNotice("Событие принято, новый вариант плана рассчитан");
  }, [data.scenarioId, loadApi, showNotice, source]);

  const comparePlans = useCallback(async (oldPlanId: string, newPlanId: string) => {
    if (source === "api") {
      const plan = await backend.plan(newPlanId);
      if (plan.based_on_plan_id !== oldPlanId) throw new Error("Детальное сравнение доступно только для связанных версий");
      await loadApi(data.scenarioId, plan.planning_date, newPlanId, true);
    }
    showNotice("Сравнение планов открыто в разделе планирования");
  }, [data.scenarioId, loadApi, showNotice, source]);

  const manualChange = useCallback(async (_requestId: string, _engineerId: string, _startAt: string) => {
    if (source === "api") apiUnavailable("Ручное изменение плана");
    else if ((import.meta.env.VITE_DEMO_MODE ?? "auto") === "true") showNotice("Демонстрационное изменение создано");
    else throw new Error("Ручное изменение требует backend endpoint");
  }, [apiUnavailable, showNotice, source]);

  const downloadReport = useCallback(async (format: "xlsx" | "pdf", planId?: string) => {
    if (source !== "api") {
      showNotice("В демо-режиме выгрузка недоступна");
      return;
    }
    const exportResult = format === "xlsx"
      ? await backend.exportPlan(planId ?? data.activePlanId)
      : await backend.exportDailyReport(data.planningDate);
    window.location.assign(exportResult.url);
    showNotice(`Загрузка ${exportResult.filename} началась`);
  }, [data.activePlanId, data.planningDate, showNotice, source]);

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
    rejectPlan,
    createUrgentRequest,
    createDayEvent,
    manualChange,
    comparePlans,
    downloadReport,
    openPlan: (planId: string) => loadApi(data.scenarioId, data.planningDate, planId, true),
    refresh: () => loadApi(data.scenarioId, data.planningDate),
    dismissError: () => setError(null),
    showNotice,
  };
}

export type PlannerController = ReturnType<typeof usePlanner>;
