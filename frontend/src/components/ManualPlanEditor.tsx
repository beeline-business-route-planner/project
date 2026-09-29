import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, Check, CheckCircle2, GripVertical, Lock, MousePointerClick, Play, Search, X } from "lucide-react";
import { backend } from "../api/services";
import { ApiError } from "../api/client";
import type {
  BackendManualCommand,
  BackendManualDataset,
  BackendManualIssue,
  BackendManualPreview,
  BackendPlanDetail,
  Engineer,
  RequestItem,
  Skill,
  Transport,
} from "../api/types";
import { skillMap, vehicleMap } from "../hooks/usePlanner";
import { SkillIcon, TransportIcon, formatTime, skillLabels, transportLabels } from "./ui";

/** Where the manual plan starts: fresh workbooks, or a candidate under review. */
export type ManualEditorSource =
  | { kind: "upload"; data: BackendManualDataset }
  | { kind: "plan"; data: BackendPlanDetail; title: string };

interface EdRequest {
  id: string;
  label: string;
  type: string;
  address: string;
  district: string;
  windowStart: string;
  windowEnd: string;
  priority: number;
  skill: Skill;
  transport: Transport | null;
  serviceMinutes: number | null;
}

interface EdEngineer {
  id: string;
  name: string;
  shiftStart: string;
  shiftEnd: string;
  skills: Skill[] | null; // null: unknown, not checked on the client
  transport: Transport;
  available: boolean;
  color: string;
}

const crewColors = ["#ffd400", "#28c6b7", "#ff7a59", "#54a7ff", "#8ed35f", "#ffb84d"];
const skillType: Record<Skill, string> = { emergency: "Авария", connection: "Подключение", local: "Локальные работы" };
const issueLabels: Record<BackendManualIssue["code"], string> = {
  unknown_request: "Заявка не найдена в исходных данных",
  duplicate_request: "Заявка назначена несколько раз",
  unknown_engineer: "Бригада не найдена",
  engineer_unavailable: "Бригада недоступна",
  skill: "Не подходит квалификация бригады",
  vehicle: "Не подходит транспорт бригады",
  window_order: "Порядок заявок противоречит временным окнам",
  no_route: "Не найден маршрут между точками",
  window_passed: "Временное окно уже прошло",
  late: "Бригада прибудет позже допустимого времени",
  shift_end: "Работа закончится после смены",
};

function manualIssues(error: unknown): BackendManualIssue[] {
  if (!(error instanceof ApiError) || !Array.isArray(error.details.issues)) return [];
  return error.details.issues.filter((issue): issue is BackendManualIssue =>
    typeof issue === "object" && issue !== null && typeof issue.request_id === "string" &&
    typeof issue.code === "string" && issue.code in issueLabels,
  );
}

function issueText(issue: BackendManualIssue): string {
  const label = issueLabels[issue.code];
  return issue.at && issue.limit
    ? `${label}: ${formatTime(issue.at)} при границе ${formatTime(issue.limit)}`
    : label;
}

function buildModel(source: ManualEditorSource, workspace?: { requests: RequestItem[]; engineers: Engineer[] }) {
  if (source.kind === "upload") {
    const requests = source.data.requests.map((item): EdRequest => {
      const skill = skillMap[item.required_skill] ?? "local";
      return {
        id: item.id, label: `BK-${item.external_id}`, type: skillType[skill], address: item.address, district: item.district,
        windowStart: item.window_start, windowEnd: item.window_end, priority: item.priority, skill,
        transport: item.required_vehicle_type ? vehicleMap[item.required_vehicle_type] ?? null : null,
        serviceMinutes: item.norm_minutes_without_travel,
      };
    });
    const engineers = source.data.engineers.map((item, index): EdEngineer => ({
      id: item.id, name: item.name, shiftStart: item.shift_start, shiftEnd: item.shift_end,
      skills: item.skills.map((skill) => skillMap[skill] ?? "local"), transport: vehicleMap[item.vehicle_type] ?? "car",
      available: item.is_available, color: crewColors[index % crewColors.length],
    }));
    return { requests, engineers, locked: {} as Record<string, string[]>, routes: {} as Record<string, string[]> };
  }
  // A candidate under review: routes and locks from the plan, attributes from the loaded workspace.
  const known = new Map(workspace?.requests.map((item) => [item.id, item]) ?? []);
  const knownCrews = new Map(workspace?.engineers.map((item) => [item.id, item]) ?? []);
  const tiles = [...new Map(source.data.request_groups.flatMap((group) => group.requests.map((item) => [item.request_id, item] as const))).values()];
  const requests = tiles.map((item): EdRequest => {
    const extra = known.get(item.request_id);
    const skill = skillMap[item.required_skill] ?? "local";
    return {
      id: item.request_id, label: `BK-${item.external_id}`, type: extra?.bk_type ?? skillType[skill], address: item.address, district: item.district,
      windowStart: item.window_start, windowEnd: item.window_end, priority: item.priority, skill,
      transport: extra?.required_transport ?? null, serviceMinutes: extra?.service_minutes ?? null,
    };
  });
  const engineers = source.data.engineers.map((item, index): EdEngineer => {
    const extra = knownCrews.get(item.engineer_id);
    return {
      id: item.engineer_id, name: item.name, shiftStart: item.shift_start, shiftEnd: item.shift_end,
      skills: extra?.skills.length ? extra.skills : null, transport: vehicleMap[item.vehicle_type] ?? "car",
      available: extra?.status !== "unavailable", color: extra?.color ?? crewColors[index % crewColors.length],
    };
  });
  const byCrew = (locked: boolean) => Object.fromEntries(source.data.engineers.map((crew) => [
    crew.engineer_id,
    [...crew.stops].sort((a, b) => (a.sequence_number ?? 0) - (b.sequence_number ?? 0)).filter((stop) => stop.is_locked === locked).map((stop) => stop.request_id),
  ]));
  return { requests, engineers, locked: byCrew(true), routes: byCrew(false) };
}

/** Why a crew cannot take a request, or null when it can (client-side hint; the server decides). */
function blockReason(request: EdRequest, crew: EdEngineer): string | null {
  if (!crew.available) return "Бригада недоступна";
  if (crew.skills && !crew.skills.includes(request.skill)) return `Нет навыка «${skillLabels[request.skill]}»`;
  if (request.transport && request.transport !== crew.transport) return `Нужен транспорт: ${transportLabels[request.transport].toLowerCase()}`;
  return null;
}

export function ManualPlanEditor({ source, workspace, hasInitialPlan, onClose, onSaved }: {
  source: ManualEditorSource;
  workspace?: { requests: RequestItem[]; engineers: Engineer[] };
  hasInitialPlan: boolean;
  onClose: () => void;
  onSaved: (planId: string) => Promise<void>;
}) {
  const model = useMemo(() => buildModel(source, workspace), [source, workspace]);
  const [routes, setRoutes] = useState<Record<string, string[]>>(model.routes);
  const [selected, setSelected] = useState<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropCrew, setDropCrew] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<BackendManualPreview | null>(null);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [issues, setIssues] = useState<BackendManualIssue[]>([]);
  const [dirty, setDirty] = useState(false);

  const requestById = useMemo(() => new Map(model.requests.map((item) => [item.id, item])), [model.requests]);
  const crewById = useMemo(() => new Map(model.engineers.map((item) => [item.id, item])), [model.engineers]);
  const lockedIds = useMemo(() => new Set(Object.values(model.locked).flat()), [model.locked]);
  const assignedIds = new Set(Object.values(routes).flat());
  const pool = model.requests
    .filter((item) => !lockedIds.has(item.id) && !assignedIds.has(item.id))
    .sort((a, b) => a.priority - b.priority || a.windowStart.localeCompare(b.windowStart));
  const term = query.trim().toLocaleLowerCase("ru");
  const visiblePool = term ? pool.filter((item) => [item.label, item.address, item.district, item.type].some((value) => value.toLocaleLowerCase("ru").includes(term))) : pool;
  const active = requestById.get(dragging ?? selected ?? "") ?? null;
  const stopById = new Map(preview?.stops.map((item) => [item.request_id, item]) ?? []);
  const issuesByRequest = new Map<string, string[]>();
  for (const issue of issues) {
    issuesByRequest.set(issue.request_id, [...(issuesByRequest.get(issue.request_id) ?? []), issueText(issue)]);
  }
  const crewsUsed = model.engineers.filter((crew) => (model.locked[crew.id]?.length ?? 0) + (routes[crew.id]?.length ?? 0) > 0).length;
  const assignedCount = lockedIds.size + assignedIds.size;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setSelected(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const change = (next: (current: Record<string, string[]>) => Record<string, string[]>) => {
    setRoutes(next);
    setPreview(null);
    setError(null);
    setIssues([]);
    setDirty(true);
  };

  /** Put a request into a crew (at a position) or back to the pool. */
  const place = (requestId: string, crewId: string | null, at?: number) => {
    const request = requestById.get(requestId);
    if (!request || lockedIds.has(requestId)) return;
    if (crewId) {
      const crew = crewById.get(crewId);
      const reason = crew ? blockReason(request, crew) : "Бригада не найдена";
      if (reason) { setError(`${request.label} нельзя отдать «${crew?.name}»: ${reason.toLowerCase()}.`); return; }
    }
    change((current) => {
      // Moving down inside the same crew: removing the stop first shifts the target up.
      const from = crewId ? (current[crewId] ?? []).indexOf(requestId) : -1;
      const target = at != null && from >= 0 && from < at ? at - 1 : at;
      const next = Object.fromEntries(Object.entries(current).map(([id, ids]) => [id, ids.filter((item) => item !== requestId)]));
      if (crewId) {
        const items = [...(next[crewId] ?? [])];
        items.splice(target ?? items.length, 0, requestId);
        next[crewId] = items;
      }
      return next;
    });
    setSelected(null);
  };

  const command = (): BackendManualCommand => ({
    ...(source.kind === "upload" ? { upload_id: source.data.upload_id } : { source_plan_id: source.data.id }),
    routes: model.engineers.map((crew) => ({ engineer_id: crew.id, request_ids: routes[crew.id] ?? [] })),
  });

  const check = async () => {
    setChecking(true);
    setError(null);
    setIssues([]);
    try { setPreview(await backend.previewManual(command())); }
    catch (failure) {
      setPreview(null);
      const found = manualIssues(failure);
      setIssues(found);
      setError(found.length ? `Найдено проблемных заявок: ${new Set(found.map((item) => item.request_id)).size}. Наведите на красные карточки, чтобы увидеть причины.` : failure instanceof Error ? failure.message : "Проверка не удалась");
    }
    finally { setChecking(false); }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const result = await backend.saveManual(command());
      await onSaved(result.plan_id);
    } catch (failure) {
      const found = manualIssues(failure);
      setIssues(found);
      setError(found.length ? "Маршрут нарушает ограничения. Наведите на красные карточки." : failure instanceof Error ? failure.message : "Сохранение не удалось");
    } finally { setSaving(false); }
  };

  const close = () => {
    if (dirty && !window.confirm("Закрыть редактор? Несохранённые изменения пропадут.")) return;
    onClose();
  };

  const delta = (value: number | string | null | undefined, unit = "") => {
    const numeric = Number(value);
    if (value == null || !Number.isFinite(numeric) || numeric === 0) return null;
    return `${numeric > 0 ? "+" : "−"}${Math.abs(numeric).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}${unit}`;
  };

  // `index` is the number shown in the crew; `insertAt` is the position among editable stops.
  const requestCard = (request: EdRequest, crewId: string | null, index: number, locked: boolean, insertAt = index) => {
    const stop = stopById.get(request.id);
    const reasons = issuesByRequest.get(request.id) ?? [];
    const isSelected = selected === request.id;
    return (
      <div
        key={request.id}
        className={["mp-req", locked ? "is-locked" : "", reasons.length ? "is-invalid" : "", isSelected ? "is-selected" : "", dragging === request.id ? "is-dragging" : ""].filter(Boolean).join(" ")}
        title={reasons.join("\n") || undefined}
        draggable={!locked}
        tabIndex={locked ? -1 : 0}
        role={locked ? undefined : "button"}
        aria-pressed={locked ? undefined : isSelected}
        aria-label={reasons.length ? `${request.label}: ${reasons.join("; ")}` : locked ? `${request.label}, закреплена` : `${request.label}, ${request.type}. ${crewId ? "Нажмите, чтобы выбрать и перенести" : "Нажмите, затем выберите бригаду"}`}
        onClick={(event) => { event.stopPropagation(); if (!locked) setSelected(isSelected ? null : request.id); }}
        onKeyDown={(event) => { if (!locked && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); setSelected(isSelected ? null : request.id); } }}
        onDragStart={(event) => { event.dataTransfer.setData("text/plain", request.id); event.dataTransfer.effectAllowed = "move"; setDragging(request.id); }}
        onDragEnd={() => { setDragging(null); setDropCrew(null); }}
        onDragOver={crewId && !locked ? (event) => { event.preventDefault(); event.stopPropagation(); setDropCrew(crewId); } : undefined}
        onDrop={crewId && !locked ? (event) => { event.preventDefault(); event.stopPropagation(); place(event.dataTransfer.getData("text/plain"), crewId, insertAt); setDropCrew(null); } : undefined}
      >
        {crewId ? <span className="mp-seq">{locked ? <Lock size={11} /> : index + 1}</span> : <span className={`priority-badge priority-${Math.min(3, request.priority)}`}>{request.priority}</span>}
        <div className="mp-req-main">
          <strong>{request.label} <small>{request.type}</small>{reasons.length ? <AlertTriangle className="mp-req-alert" size={14} aria-hidden="true" /> : null}</strong>
          <span>{request.address}</span>
          <em>
            окно {formatTime(request.windowStart)}–{formatTime(request.windowEnd)}
            {stop ? <> · <b>работа {formatTime(stop.planned_start)}–{formatTime(stop.planned_finish)}</b>{stop.travel_minutes ? `, дорога ${stop.travel_minutes} мин` : ""}</> : null}
            {locked ? " · уже начата, не меняется" : null}
          </em>
        </div>
        {reasons.length ? <div className="mp-req-tooltip" role="tooltip">{reasons.map((reason) => <span key={reason}>{reason}</span>)}</div> : null}
        {!locked ? (
          <div className="mp-req-tools">
            {crewId ? <GripVertical size={15} className="mp-grip" aria-hidden="true" /> : null}
            {crewId ? <button type="button" className="mp-remove" aria-label={`Снять ${request.label} с бригады`} title="Вернуть в «Без назначения»" onClick={(event) => { event.stopPropagation(); place(request.id, null); }}><X size={14} /></button> : null}
          </div>
        ) : null}
      </div>
    );
  };

  const scopeText = source.kind === "upload"
    ? `Новый план из файлов · ${source.data.planning_date}`
    : `Правка версии «${source.title}»`;

  return (
    <div className="mp-overlay" role="dialog" aria-modal="true" aria-label="Ручное планирование" onClick={() => setSelected(null)}>
      <header className="mp-head">
        <button type="button" className="button ghost" onClick={close}><ArrowLeft size={16} /> Назад</button>
        <div className="mp-title">
          <span className="eyebrow">Ручное планирование</span>
          <h2>{scopeText}</h2>
        </div>
        {hasInitialPlan ? <div className="mp-stats" aria-live="polite">
          <div><small>Назначено</small><b>{assignedCount} <span>из {model.requests.length}</span></b>{preview ? <em>{delta(preview.assigned_delta)}</em> : null}</div>
          <div><small>Бригад</small><b>{crewsUsed} <span>из {model.engineers.length}</span></b>{preview ? <em>{delta(preview.engineers_used_delta)}</em> : null}</div>
          <div><small>Пробег</small><b>{preview ? `${Number(preview.total_mileage_km).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} км` : "—"}</b>{preview ? <em>{delta(preview.mileage_delta_km, " км")}</em> : null}</div>
          <span className={`mp-state ${preview ? "is-ok" : ""}`}>{preview ? <><CheckCircle2 size={14} />Проверено</> : checking ? "Проверяем…" : dirty ? "Не проверено" : "Без изменений"}</span>
        </div> : null}
        <div className="mp-actions">
          <button type="button" className="button secondary" disabled={checking || saving} onClick={() => void check()}><Play size={15} />{checking ? "Проверяем…" : "Проверить"}</button>
          <button type="button" className="button primary" disabled={saving || checking} onClick={() => void save()}><Check size={16} />{saving ? "Сохраняем…" : "Сохранить версию"}</button>
        </div>
      </header>

      {error ? <div className="mp-error" role="alert"><AlertTriangle size={16} />{error}<button type="button" aria-label="Скрыть" onClick={() => setError(null)}><X size={14} /></button></div> : null}
      <p className="mp-hint">
        <MousePointerClick size={15} />
        {active ? <>Выбрана <b>{active.label}</b> — нажмите на бригаду, чтобы отдать её. Неподходящие бригады приглушены. Esc — отменить.</> : "Перетащите заявку на бригаду или нажмите на заявку, а затем на бригаду. Порядок внутри бригады меняется перетаскиванием. Время и дорогу посчитает сервер при проверке."}
      </p>

      <div className="mp-body">
        <aside
          className={`mp-pool ${dragging && dropCrew === "pool" ? "is-drop" : ""}`}
          onDragOver={(event) => { event.preventDefault(); setDropCrew("pool"); }}
          onDragLeave={() => setDropCrew(null)}
          onDrop={(event) => { event.preventDefault(); place(event.dataTransfer.getData("text/plain"), null); setDropCrew(null); }}
          onClick={(event) => { if (selected && assignedIds.has(selected)) { event.stopPropagation(); place(selected, null); } }}
        >
          <div className="mp-pool-head"><h3>Без назначения</h3><span>{pool.length}</span></div>
          <label className="search-field mp-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Номер, адрес, район" onClick={(event) => event.stopPropagation()} /></label>
          <div className="mp-pool-list">
            {visiblePool.map((request) => requestCard(request, null, 0, false))}
            {!pool.length ? <p className="mp-empty"><CheckCircle2 size={16} />Все заявки распределены</p> : !visiblePool.length ? <p className="mp-empty">Ничего не найдено</p> : null}
          </div>
          {selected && assignedIds.has(selected) ? <p className="mp-pool-drop">Нажмите сюда, чтобы снять выбранную заявку с бригады</p> : null}
        </aside>

        <div className="mp-crews">
          {model.engineers.map((crew) => {
            const locked = model.locked[crew.id] ?? [];
            const stops = routes[crew.id] ?? [];
            const reason = active ? blockReason(active, crew) : null;
            const crewKm = [...locked, ...stops].reduce((sum, id) => sum + Number(stopById.get(id)?.distance_km ?? 0), 0);
            return (
              <section
                key={crew.id}
                className={["mp-crew", reason ? "is-blocked" : "", active && !reason ? "is-target" : "", dropCrew === crew.id && dragging ? (reason ? "is-drop-bad" : "is-drop") : ""].filter(Boolean).join(" ")}
                style={{ ["--crew" as string]: crew.color }}
                onDragOver={(event) => { event.preventDefault(); setDropCrew(crew.id); }}
                onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDropCrew(null); }}
                onDrop={(event) => { event.preventDefault(); place(event.dataTransfer.getData("text/plain"), crew.id); setDropCrew(null); }}
                onClick={(event) => { if (selected) { event.stopPropagation(); place(selected, crew.id); } }}
              >
                <div className="mp-crew-head">
                  <i className="mp-crew-dot" />
                  <div>
                    <strong>{crew.name}</strong>
                    <span><TransportIcon transport={crew.transport} size={13} /> {transportLabels[crew.transport]} · {formatTime(crew.shiftStart)}–{formatTime(crew.shiftEnd)}</span>
                  </div>
                  <div className="mp-crew-skills">{crew.skills?.map((skill) => <i key={skill} title={skillLabels[skill]}><SkillIcon skill={skill} size={13} /></i>)}</div>
                </div>
                <div className="mp-crew-meta">
                  <span>{locked.length + stops.length} {locked.length + stops.length === 1 ? "заявка" : "заявок"}</span>
                  {preview ? <span>{crewKm.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} км</span> : null}
                  {!crew.available ? <span className="mp-bad">недоступна</span> : null}
                  {reason && active ? <span className="mp-bad">{reason}</span> : null}
                </div>
                <div className="mp-crew-stops">
                  {locked.map((id, index) => { const request = requestById.get(id); return request ? requestCard(request, crew.id, index, true) : null; })}
                  {stops.map((id, index) => { const request = requestById.get(id); return request ? requestCard(request, crew.id, locked.length + index, false, index) : null; })}
                  {!locked.length && !stops.length ? <p className="mp-empty">Перетащите сюда заявку</p> : null}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}
