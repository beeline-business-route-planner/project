export type RequestStatus =
  | "NOT_SENT"
  | "SENT"
  | "EN_ROUTE"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "OVERDUE"
  | "CANCELLED";

export type PlanStatus = "draft" | "approved" | "superseded" | "rejected";
export type Priority = "normal" | "urgent";
export type Transport = "car" | "walking" | "bicycle" | "transit";
export type Skill = "connection" | "emergency" | "local";

export interface Scenario {
  id: string;
  code: string;
  name: string;
  timezone: string;
  planning_dates: string[];
}

export interface RequestItem {
  id: string;
  external_id: string;
  bk_type: string;
  hd_type: string;
  address: string;
  district: string;
  coordinates: [number, number];
  window_start: string;
  window_end: string;
  service_minutes: number;
  full_normative_minutes: number;
  status: RequestStatus;
  mapping_state: "mapped" | "unmapped";
  priority: Priority;
  priority_rank: 1 | 2 | 3;
  required_skill: Skill;
  required_transport: Transport | null;
  /** Connection technology from the request card, e.g. "FTTB". */
  connection_type: string | null;
  is_gigabit: boolean;
  /** When the request was loaded into the system (`created_at` of the card). */
  created_at: string | null;
  engineer_id: string | null;
  engineer_name: string | null;
  arrival_at: string | null;
  /** Planned work interval and travel to this stop (from the plan). */
  planned_start: string | null;
  planned_finish: string | null;
  travel_minutes: number | null;
  explanation: string;
  unassigned_reason?: string;
}

export interface Engineer {
  id: string;
  name: string;
  transport: Transport;
  skills: Skill[];
  status: "available" | "en_route" | "working" | "unavailable";
  request_ids: string[];
  shift_start: string | null;
  shift_end: string | null;
  /** Office or remote "home" the engineer starts the day from. */
  start_address: string | null;
  /** Share of the shift busy with work and travel, 0–100+ (from the plan). */
  load_percent: number;
  /** Share of the shift busy with work only; travel = load_percent − work_percent. */
  work_percent: number;
  distance_meters: number;
  color: string;
}

export interface LineString {
  type: "LineString";
  coordinates: [number, number][];
}

export interface RouteOverview {
  engineer_id: string;
  profile: string;
  route_status: "ready" | "empty";
  provider: string;
  graph_fingerprint: string;
  geometry: LineString | null;
  /** Office the engineer starts from; the map draws it as a flag. */
  start_coordinates?: [number, number] | null;
  distance_meters: number;
  duration_seconds: number;
}

export interface OverviewRoutesResponse {
  plan_id: string;
  revision: string;
  status: string;
  routes: RouteOverview[];
}

export interface RouteStop {
  sequence: number;
  location_id: string;
  request_id: string | null;
  coordinates: [number, number];
  snapped_coordinates: [number, number];
}

export interface RouteSegment {
  sequence: number;
  key: string;
  from_location_id: string;
  to_location_id: string;
  distance_meters: number;
  duration_seconds: number;
  metrics_source: "route" | "matrix";
  point_start: number;
  point_end: number;
}

export interface DetailedRoute extends RouteOverview {
  plan_id: string;
  revision: string;
  status: string;
  stops: RouteStop[];
  segments: RouteSegment[];
}

export interface PlanAssignment {
  request_id: string;
  request_external_id: string;
  engineer_id: string;
  engineer: string;
  position: number;
  address: string;
  arrival_at: string;
  start_at: string;
  finish_at: string;
  travel_seconds: number;
  distance_meters: number;
  explanation: string;
}

export interface UnassignedRequest {
  request_id: string;
  request_external_id: string;
  reason_code: string;
  explanation: string;
}

export interface StoredPlanRoute {
  engineer_id: string;
  profile: string;
  geometry: (LineString & { provider?: string | null }) | null;
  route_status?: "ready" | "empty";
  provider?: string;
  graph_fingerprint?: string;
  distance_meters?: number;
  duration_seconds?: number;
}

export interface PlanDetails {
  id: string;
  scenario_id: string;
  planning_date: string;
  status: PlanStatus;
  parent_plan_id: string | null;
  base_plan_id: string | null;
  input_version: string;
  assignments: PlanAssignment[];
  unassigned: UnassignedRequest[];
  metrics: Record<string, number | string | null>;
  routes: StoredPlanRoute[];
  warnings: string[];
}

export interface PlanningRun {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  algorithm: string;
  input_version: string;
  plan_id: string | null;
  failure: { code: string; message?: string | null } | null;
  started_at: string;
  finished_at: string | null;
}

export interface PlanSummary {
  id: string;
  /** Human name: what created the version and when, e.g. "Пересчёт по событию · 17:05". */
  title: string;
  kind?: "initial" | "replan" | "event_replan";
  is_current?: boolean;
  status: PlanStatus;
  parent_plan_id: string | null;
  base_plan_id: string | null;
  input_version: string;
  created_at: string;
  approved_at?: string | null;
  requests_count: number;
  assigned_count: number;
  distance_meters?: number;
}

export interface PlanDiffItem {
  request_id: string;
  external_id: string;
  changes: string[];
  old_engineer: string | null;
  new_engineer: string | null;
  old_start: string | null;
  new_start: string | null;
  state: "new" | "changed" | "removed";
}

export interface PlanMetrics {
  assigned: number;
  unassigned: number;
  completed: number;
  engineers_used: number;
  distance_meters: number;
  avg_load_percent: number;
  coverage_percent: number;
  /** Totals of the plan (absent in demo data). */
  work_minutes?: number;
  travel_minutes?: number;
  available_engineers?: number;
  min_load_percent?: number;
  max_load_percent?: number;
}

/** Metrics of the initial plan and of the baseline algorithm from the spec (п. 2.3). */
export interface BaselineComparison {
  plan: { engineers_used: number; distance_km: number; assigned: number };
  baseline: { engineers_used: number; distance_km: number; assigned: number };
}

export interface AuditItem {
  id: string;
  timestamp: string;
  actor: string;
  action: string;
  entity: string;
  entity_id: string;
  details: string;
}

export interface ApiAuditItem {
  id: string;
  action: string;
  actor: string;
  source?: string;
  effective_at: string;
  recorded_at?: string;
  object_type: string;
  object_id?: string | null;
  reason?: string | null;
  details: Record<string, unknown> | string;
}

export interface ApiPlanDiffItem {
  request_id: string;
  changes: string[];
  old: {
    engineer_id: string;
    position: number;
    start_at: string;
    finish_at: string;
  } | null;
  new: {
    engineer_id: string;
    position: number;
    start_at: string;
    finish_at: string;
  } | null;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  detail: string | { msg: string }[];
  details: Record<string, unknown>;
  correlation_id: string;
}

export interface WorkspaceData {
  scenarios: Scenario[];
  scenarioId: string;
  planningDate: string;
  activePlanId: string;
  requests: RequestItem[];
  engineers: Engineer[];
  plans: PlanSummary[];
  routes: OverviewRoutesResponse;
  metrics: PlanMetrics;
  audit: AuditItem[];
  diff: PlanDiffItem[];
  /** "Was → became" metrics of the candidate against its base; absent for initial. */
  diffSummary?: PlanDiffMetric[];
  /** How many requests the diff compared (changed or not). */
  diffCompared?: number;
}

export interface PlanDiffMetric {
  key: string;
  label: string;
  before: number;
  after: number;
  delta: number;
  unit: string;
  /** Which direction is an improvement, for colouring the delta. */
  better: "up" | "down";
}

export type BackendRegion = "vostok" | "yugo_vostok" | "yugotsentr";
export type BackendEventType = "urgent_request" | "request_cancelled" | "engineer_unavailable" | "engineer_available";
export interface BackendUrgentRequest {
  external_id: number;
  type_bk: "global_problem" | "additional_order" | "local_request" | "connection";
  type_hd: "emergency" | "connection_request";
  district: string;
  address: string;
  connection_type: null;
  is_gigabit: boolean;
  window_start: string;
  window_end: string;
  norm_minutes: number;
  norm_minutes_without_travel: number;
  priority: 1 | 2;
  required_skill: BackendSkill;
  required_vehicle_type: BackendVehicle | null;
}
export interface BackendPlanningEvent {
  region: BackendRegion;
  event_type: BackendEventType;
  request_id?: string;
  engineer_id?: string;
  urgent_request?: BackendUrgentRequest;
}
export interface BackendPlanningResult {
  status: string;
  regions: Array<{ region: BackendRegion; status: string; plan_summary: Pick<BackendPlanSummary, "id" | "region" | "planning_date"> | null; error: { code: string; detail: string } | null }>;
}
export interface BackendEventResult { event_id: string; event_type: BackendEventType; plan: Pick<BackendPlanSummary, "id" | "region" | "planning_date"> }
export interface BackendExport { url: string; expires_at: string; filename: string; content_type: string; size_bytes: number }
export type BackendSkill =
  | "local_works"
  | "connection_and_orders"
  | "emergency_works";
export type BackendVehicle = "car" | "pedestrian" | "bicycle" | "public_transport";

export interface BackendInitialPlanningResponse {
  status: "success" | "partial_success" | "error";
  regions: Array<{
    region: BackendRegion;
    status: "success" | "error";
    plan_summary: {
      id: string;
      region: BackendRegion;
      kind: "initial";
      approval_status: "pending";
      planning_date: string;
      created_at: string;
      approval_deadline: string;
      assigned_requests_count: number;
      unassigned_requests_count: number;
      engineers_used_count: number;
      total_mileage_km: number | string;
    } | null;
    error: { code: string; detail: string } | null;
  }>;
}

export interface BackendRequestTile {
  request_id: string;
  external_id: number;
  address: string;
  district: string;
  latitude: number | string | null;
  longitude: number | string | null;
  window_start: string;
  window_end: string;
  priority: number;
  required_skill: BackendSkill;
  planned_arrival: string | null;
  planned_start: string | null;
  planned_finish: string | null;
  sequence_number: number | null;
  travel_minutes: number | null;
  distance_km: number | string | null;
  is_locked: boolean;
  assigned_engineer: { engineer_id: string; name: string } | null;
  engineer_id?: string | null;
  unassigned_reason: string | null;
}

export interface BackendPlanMetrics {
  assigned_requests_count: number;
  unassigned_requests_count: number;
  engineers_used_count: number;
  available_engineers_count: number;
  total_mileage_km: number | string;
  total_work_minutes: number;
  total_travel_minutes: number;
  average_workload_without_travel: number | string;
  average_workload_with_travel: number | string;
  average_used_workload_without_travel: number | string;
  average_used_workload_with_travel: number | string;
  min_workload_with_travel: number | string;
  max_workload_with_travel: number | string;
}

export interface BackendEngineerTile {
  engineer_id: string;
  name: string;
  vehicle_type: BackendVehicle;
  shift_start: string;
  shift_end: string;
  start_latitude: number | string | null;
  start_longitude: number | string | null;
  assigned_requests_count: number;
  route_distance_km: number | string;
  workload_without_travel: number | string;
  workload_with_travel: number | string;
  stops: BackendRequestTile[];
}

export interface BackendPlanDiff {
  /** Plan-level metrics of the base (before) and candidate (after) versions. */
  summary?: Record<string, { before: number | string; after: number | string; delta: number | string }>;
  requests: Array<{
    request_id: string;
    changes: string[];
    before: BackendRequestTile | null;
    after: BackendRequestTile | null;
  }>;
}

export interface BackendPlanDetail {
  id: string;
  region: BackendRegion;
  planning_date: string;
  kind: "initial" | "replan" | "event_replan";
  approval_status: "pending" | "approved" | "rejected";
  created_at: string;
  approved_at: string | null;
  rejected_at: string | null;
  approval_deadline: string | null;
  is_current: boolean;
  can_approve: boolean;
  can_reject: boolean;
  calculation_cutoff_at: string;
  based_on_plan_id: string | null;
  triggered_by_event_id: string | null;
  edited_from_plan_id?: string | null;
  metrics: BackendPlanMetrics;
  baseline_metrics?: {
    assigned_requests_count: number;
    unassigned_requests_count: number;
    engineers_used_count: number;
    total_mileage_km: number | string;
    average_workload_with_travel: number | string;
    average_workload_without_travel: number | string;
    algorithm_version: string;
  } | null;
  request_groups: Array<{ group: string; requests: BackendRequestTile[] }>;
  engineers: BackendEngineerTile[];
  diff: BackendPlanDiff | null;
}

export interface BackendPlanSummary {
  id: string;
  region: BackendRegion;
  planning_date: string;
  kind: "initial" | "replan" | "event_replan";
  strategy: "lns" | "layered_graph" | "greedy" | "manual";
  approval_status: "pending" | "approved" | "rejected";
  created_at: string;
  approved_at: string | null;
  rejected_at: string | null;
  approval_deadline: string | null;
  based_on_plan_id: string | null;
  triggered_by_event_id: string | null;
  edited_from_plan_id?: string | null;
  is_current: boolean;
  assigned_requests_count: number;
  unassigned_requests_count: number;
  engineers_used_count: number;
  total_mileage_km: number | string;
}

export interface BackendManualDataset {
  upload_id: string;
  region: BackendRegion;
  planning_date: string;
  requests: Array<{
    id: string;
    external_id: number;
    address: string;
    district: string;
    latitude: number | string | null;
    longitude: number | string | null;
    window_start: string;
    window_end: string;
    priority: number;
    required_skill: BackendSkill;
    required_vehicle_type: BackendVehicle | null;
    norm_minutes_without_travel: number;
  }>;
  engineers: Array<{
    id: string;
    name: string;
    shift_start: string;
    shift_end: string;
    skills: BackendSkill[];
    vehicle_type: BackendVehicle;
    is_available: boolean;
  }>;
}

export interface BackendManualCommand {
  upload_id?: string;
  source_plan_id?: string;
  routes: Array<{ engineer_id: string; request_ids: string[] }>;
}

export interface BackendManualPreview {
  assigned_requests_count: number;
  unassigned_requests_count: number;
  engineers_used_count: number;
  total_mileage_km: number | string;
  stops: Array<{
    request_id: string;
    engineer_id: string;
    sequence_number: number;
    planned_arrival: string;
    planned_start: string;
    planned_finish: string;
    travel_minutes: number;
    distance_km: number | string;
    is_locked: boolean;
  }>;
  compared_to_plan_id: string | null;
  assigned_delta: number | null;
  engineers_used_delta: number | null;
  mileage_delta_km: number | string | null;
}

export interface BackendManualIssue {
  request_id: string;
  engineer_id: string | null;
  code: "unknown_request" | "duplicate_request" | "unknown_engineer" | "engineer_unavailable" | "skill" | "vehicle" | "window_order" | "no_route" | "window_passed" | "late" | "shift_end";
  at: string | null;
  limit: string | null;
}

export interface BackendEngineerDetail {
  id: string;
  name: string;
  region: BackendRegion;
  start_point_address: string;
  start_point_latitude: number | string | null;
  start_point_longitude: number | string | null;
  shift_start: string;
  shift_end: string;
  skills: BackendSkill[];
  vehicle_type: BackendVehicle;
  is_available: boolean;
  created_at: string;
}

export interface BackendRequestDetail {
  id: string;
  external_id: number;
  type_bk: string;
  type_hd: string;
  region: BackendRegion;
  district: string;
  address: string;
  latitude: number | string | null;
  longitude: number | string | null;
  connection_type: "fmc" | "fttb" | null;
  is_gigabit: boolean;
  window_start: string;
  window_end: string;
  norm_minutes: number;
  norm_minutes_without_travel: number;
  priority: number;
  required_skill: BackendSkill;
  required_vehicle_type: BackendVehicle | null;
  status: "not_sent" | "sent" | "on_the_way" | "in_progress" | "done" | "cancelled" | "overdue";
  created_at: string;
}
