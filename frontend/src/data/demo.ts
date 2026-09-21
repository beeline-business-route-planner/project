import type {
  AuditItem,
  DetailedRoute,
  Engineer,
  OverviewRoutesResponse,
  PlanDiffItem,
  PlanSummary,
  RequestItem,
  Scenario,
  WorkspaceData,
} from "../api/types";

const date = "2026-08-17";
const at = (time: string) => `${date}T${time}:00+03:00`;

export const demoScenarios: Scenario[] = [
  {
    id: "scenario-south-east",
    code: "south-east",
    name: "Юго-восток",
    timezone: "Europe/Moscow",
    planning_dates: [date],
  },
  {
    id: "scenario-east",
    code: "east",
    name: "Восток",
    timezone: "Europe/Moscow",
    planning_dates: [date],
  },
  {
    id: "scenario-south-center",
    code: "south-center",
    name: "Югоцентр",
    timezone: "Europe/Moscow",
    planning_dates: [date],
  },
];

export const demoEngineers: Engineer[] = [
  {
    id: "eng-01",
    external_code: "ENG-014",
    name: "Антон Волков",
    transport: "car",
    skills: ["emergency", "connection", "local"],
    status: "working",
    request_ids: ["req-01", "req-02", "req-03"],
    load_minutes: 336,
    distance_meters: 27800,
    color: "#6f4cff",
  },
  {
    id: "eng-02",
    external_code: "ENG-027",
    name: "Мария Орлова",
    transport: "transit",
    skills: ["connection", "local"],
    status: "en_route",
    request_ids: ["req-04", "req-05"],
    load_minutes: 290,
    distance_meters: 19400,
    color: "#008f8c",
  },
  {
    id: "eng-03",
    external_code: "ENG-031",
    name: "Илья Серов",
    transport: "car",
    skills: ["emergency", "local"],
    status: "available",
    request_ids: ["req-06", "req-07"],
    load_minutes: 254,
    distance_meters: 22600,
    color: "#e16c2b",
  },
  {
    id: "eng-04",
    external_code: "ENG-042",
    name: "Елена Белова",
    transport: "walking",
    skills: ["connection", "local"],
    status: "working",
    request_ids: ["req-08", "req-09", "req-10"],
    load_minutes: 318,
    distance_meters: 9800,
    color: "#2879d0",
  },
  {
    id: "eng-05",
    external_code: "ENG-055",
    name: "Денис Ким",
    transport: "bicycle",
    skills: ["local"],
    status: "available",
    request_ids: ["req-11", "req-12"],
    load_minutes: 214,
    distance_meters: 12100,
    color: "#b66b00",
  },
  {
    id: "eng-06",
    external_code: "ENG-061",
    name: "Ольга Миронова",
    transport: "car",
    skills: ["emergency", "connection"],
    status: "unavailable",
    request_ids: [],
    load_minutes: 0,
    distance_meters: 0,
    color: "#bd3d77",
  },
];

type RequestSeed = [
  string,
  string,
  string,
  string,
  [number, number],
  string,
  string,
  RequestItem["status"],
  RequestItem["required_skill"],
  RequestItem["priority_rank"],
  string | null,
];

const seeds: RequestSeed[] = [
  ["req-01", "BK-84721", "Авария", "Рязанский", [37.7618, 55.7166], "09:00", "10:40", "COMPLETED", "emergency", 1, "eng-01"],
  ["req-02", "BK-84738", "Подключение", "Кузьминки", [37.7767, 55.7049], "11:00", "13:00", "IN_PROGRESS", "connection", 2, "eng-01"],
  ["req-03", "BK-84802", "Локальная", "Люблино", [37.7646, 55.6768], "14:00", "16:00", "SENT", "local", 3, "eng-01"],
  ["req-04", "BK-84746", "Подключение", "Лефортово", [37.7042, 55.7577], "10:00", "12:00", "COMPLETED", "connection", 2, "eng-02"],
  ["req-05", "BK-84791", "Локальная", "Нижегородский", [37.7285, 55.7316], "13:00", "15:00", "EN_ROUTE", "local", 3, "eng-02"],
  ["req-06", "BK-84757", "Авария", "Текстильщики", [37.7427, 55.7089], "12:10", "13:50", "COMPLETED", "emergency", 1, "eng-03"],
  ["req-07", "BK-84811", "Локальная", "Печатники", [37.7282, 55.6837], "15:00", "17:00", "SENT", "local", 3, "eng-03"],
  ["req-08", "BK-84768", "Подключение", "Марьино", [37.7471, 55.6498], "09:00", "11:00", "COMPLETED", "connection", 2, "eng-04"],
  ["req-09", "BK-84775", "Локальная", "Братиславский", [37.7533, 55.6631], "11:30", "13:30", "COMPLETED", "local", 3, "eng-04"],
  ["req-10", "BK-84819", "Дозаказ", "Люблино", [37.7394, 55.6864], "14:30", "16:00", "IN_PROGRESS", "local", 3, "eng-04"],
  ["req-11", "BK-84783", "Локальная", "Выхино", [37.8175, 55.7182], "10:00", "12:00", "COMPLETED", "local", 3, "eng-05"],
  ["req-12", "BK-84828", "Локальная", "Жулебино", [37.8551, 55.6851], "13:00", "15:00", "OVERDUE", "local", 3, "eng-05"],
  ["req-13", "BK-84844", "Подключение", "Некрасовка", [37.9208, 55.7041], "15:00", "18:00", "NOT_SENT", "connection", 2, null],
  ["req-14", "BK-84851", "Локальная", "Капотня", [37.7989, 55.6413], "16:00", "18:00", "CANCELLED", "local", 3, null],
];

export const demoRequests: RequestItem[] = seeds.map(
  ([id, externalId, type, district, coordinates, start, end, status, skill, rank, engineerId], index) => {
    const engineer = demoEngineers.find((item) => item.id === engineerId) ?? null;
    const serviceMinutes = type === "Авария" ? 100 : type === "Подключение" ? 90 : type === "Дозаказ" ? 40 : 50;
    return {
      id,
      external_id: externalId,
      bk_type: type,
      hd_type: index % 2 ? "Service Request" : "Incident",
      address: `${district}, ${["ул. Зеленодольская", "пр-т Рязанский", "ул. Совхозная", "ул. Люблинская"][index % 4]}, ${8 + index * 3}`,
      district,
      coordinates,
      window_start: at(start),
      window_end: at(end),
      service_minutes: serviceMinutes,
      full_normative_minutes: serviceMinutes,
      status,
      mapping_state: "mapped",
      priority: rank < 3 ? "urgent" : "normal",
      priority_rank: rank,
      required_skill: skill,
      required_transport: rank === 1 ? "car" : null,
      engineer_id: engineerId,
      engineer_name: engineer?.name ?? null,
      arrival_at: engineer ? at(start) : null,
      explanation: engineer
        ? `Назначен по квалификации «${skill}», допустимому временному окну и минимальному приросту маршрута.`
        : "Не назначена: у доступных инженеров нет совместимого окна до конца смены.",
      unassigned_reason: engineer ? undefined : "Нет совместимого временного окна",
    };
  },
);

const office: [number, number] = [37.7581, 55.7187];
const routeCoordinates = (engineerId: string) => {
  const stops = demoRequests
    .filter((request) => request.engineer_id === engineerId)
    .map((request) => request.coordinates);
  return [office, ...stops] as [number, number][];
};

export const demoRoutes: OverviewRoutesResponse = {
  plan_id: "plan-approved",
  revision: "rev-a17f9",
  status: "approved",
  routes: demoEngineers.map((engineer) => ({
    engineer_id: engineer.id,
    profile: engineer.transport === "car" ? "driving" : engineer.transport,
    route_status: engineer.request_ids.length ? "ready" : "empty",
    provider: "osrm",
    graph_fingerprint: "moscow-2026-08",
    geometry: engineer.request_ids.length
      ? { type: "LineString" as const, coordinates: routeCoordinates(engineer.id) }
      : null,
    distance_meters: engineer.distance_meters,
    duration_seconds: Math.round(engineer.distance_meters / 7.2),
  })),
};

export function getDemoDetailedRoute(engineerId: string): DetailedRoute {
  const route = demoRoutes.routes.find((item) => item.engineer_id === engineerId)!;
  const requests = demoRequests.filter((request) => request.engineer_id === engineerId);
  const detailedCoordinates = route.geometry?.coordinates.flatMap((point, index, points) => {
    const next = points[index + 1];
    if (!next) return [point];
    return [
      point,
      [(point[0] * 2 + next[0]) / 3, (point[1] * 2 + next[1]) / 3],
      [(point[0] + next[0] * 2) / 3, (point[1] + next[1] * 2) / 3],
    ] as [number, number][];
  });
  return {
    ...route,
    plan_id: demoRoutes.plan_id,
    revision: demoRoutes.revision,
    status: demoRoutes.status,
    geometry: detailedCoordinates
      ? { type: "LineString", coordinates: detailedCoordinates }
      : null,
    stops: requests.map((request, index) => ({
      sequence: index + 1,
      location_id: `loc-${request.id}`,
      request_id: request.id,
      coordinates: request.coordinates,
      snapped_coordinates: request.coordinates,
    })),
    segments: requests.map((request, index) => ({
      sequence: index + 1,
      key: `segment-${engineerId}-${index}`,
      from_location_id: index ? `loc-${requests[index - 1].id}` : "office",
      to_location_id: `loc-${request.id}`,
      distance_meters: Math.round(route.distance_meters / Math.max(requests.length, 1)),
      duration_seconds: Math.round(route.duration_seconds / Math.max(requests.length, 1)),
      metrics_source: "route",
      point_start: index * 3,
      point_end: index * 3 + 3,
    })),
  };
}

export const demoPlans: PlanSummary[] = [
  { id: "plan-draft", code: "PLN-1708-04", status: "draft", parent_plan_id: "plan-approved", base_plan_id: "plan-approved", input_version: "sha256:84a7", created_at: at("14:18"), requests_count: 14, assigned_count: 13 },
  { id: "plan-approved", code: "PLN-1708-03", status: "approved", parent_plan_id: "plan-old", base_plan_id: "plan-old", input_version: "sha256:2cd1", created_at: at("08:12"), approved_at: at("08:19"), requests_count: 14, assigned_count: 12 },
  { id: "plan-old", code: "PLN-1708-02", status: "superseded", parent_plan_id: "plan-first", base_plan_id: "plan-first", input_version: "sha256:c938", created_at: at("07:56"), approved_at: at("08:03"), requests_count: 13, assigned_count: 11 },
  { id: "plan-first", code: "PLN-1708-01", status: "superseded", parent_plan_id: null, base_plan_id: null, input_version: "sha256:092b", created_at: at("07:42"), approved_at: at("07:48"), requests_count: 13, assigned_count: 10 },
];

export const demoDiff: PlanDiffItem[] = [
  { request_id: "req-13", external_id: "BK-84844", changes: ["engineer", "start_at"], old_engineer: null, new_engineer: "Ольга Миронова", old_start: null, new_start: at("16:20"), state: "new" },
  { request_id: "req-07", external_id: "BK-84811", changes: ["engineer", "start_at"], old_engineer: "Илья Серов", new_engineer: "Антон Волков", old_start: at("15:00"), new_start: at("16:05"), state: "changed" },
  { request_id: "req-12", external_id: "BK-84828", changes: ["start_at"], old_engineer: "Денис Ким", new_engineer: "Денис Ким", old_start: at("13:00"), new_start: at("13:35"), state: "changed" },
];

export const demoAudit: AuditItem[] = [
  { id: "audit-1", timestamp: at("14:18"), actor: "dispatcher", action: "Перепланирование", entity: "План", entity_id: "PLN-1708-04", details: "Новая срочная заявка BK-84844" },
  { id: "audit-2", timestamp: at("13:52"), actor: "dispatcher", action: "Статус изменён", entity: "Заявка", entity_id: "BK-84819", details: "В работе" },
  { id: "audit-3", timestamp: at("12:16"), actor: "system", action: "Маршрут уточнён", entity: "Инженер", entity_id: "ENG-031", details: "OSRM, revision rev-a17f9" },
  { id: "audit-4", timestamp: at("08:19"), actor: "dispatcher", action: "План утверждён", entity: "План", entity_id: "PLN-1708-03", details: "12 из 14 заявок назначено" },
  { id: "audit-5", timestamp: at("08:12"), actor: "planner", action: "План рассчитан", entity: "План", entity_id: "PLN-1708-03", details: "Время расчёта 2,8 с" },
  { id: "audit-6", timestamp: at("07:39"), actor: "dispatcher", action: "Данные импортированы", entity: "Dataset", entity_id: "DS-17-08", details: "14 заявок, ошибок нет" },
];

export const demoWorkspace: WorkspaceData = {
  scenarios: demoScenarios,
  scenarioId: demoScenarios[0].id,
  planningDate: date,
  activePlanId: "plan-approved",
  requests: demoRequests,
  engineers: demoEngineers,
  plans: demoPlans,
  routes: demoRoutes,
  metrics: {
    assigned: 12,
    unassigned: 2,
    completed: 6,
    engineers_used: 5,
    distance_meters: 91700,
    avg_load_percent: 71,
    on_time_percent: 92,
  },
  audit: demoAudit,
  diff: demoDiff,
};
