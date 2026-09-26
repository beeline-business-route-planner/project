import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronRight,
  Clock3,
  Filter,
  MapPin,
  Plus,
  Search,
  Siren,
  SlidersHorizontal,
  UserRoundCheck,
  X,
} from "lucide-react";
import { ArrowUpRightIcon } from "@phosphor-icons/react/dist/csr/ArrowUpRight";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { TimerIcon } from "@phosphor-icons/react/dist/csr/Timer";
import { UsersThreeIcon } from "@phosphor-icons/react/dist/csr/UsersThree";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import type { RequestStatus } from "../api/types";
import type { PlannerController } from "../hooks/usePlanner";
import { MapPanel } from "../components/MapPanel";
import {
  Avatar,
  SkillIcon,
  StatusPill,
  TransportIcon,
  formatDistance,
  formatTime,
  skillLabels,
  statusLabels,
  transportLabels,
} from "../components/ui";

type ListTab = "requests" | "engineers";

export function Dashboard({ planner }: { planner: PlannerController }) {
  const { data } = planner;
  const today = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
  const canOperate = planner.source === "api" && data.planningDate === today
    && data.plans.some((plan) => plan.status === "approved" && plan.planning_date === today);
  const [tab, setTab] = useState<ListTab>("requests");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<RequestStatus | "all">("all");
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>("req-02");
  const [selectedEngineerId, setSelectedEngineerId] = useState<string | null>("eng-01");
  const [urgentOpen, setUrgentOpen] = useState(false);
  const [availableOnly, setAvailableOnly] = useState(false);

  const selectedRequest = data.requests.find((item) => item.id === selectedRequestId) ?? null;
  const selectedEngineer = data.engineers.find((item) => item.id === selectedEngineerId) ?? null;
  const filteredRequests = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("ru");
    return data.requests.filter((request) => {
      const matchesSearch = !term || [request.external_id, request.address, request.district, request.bk_type]
        .some((value) => value.toLocaleLowerCase("ru").includes(term));
      return matchesSearch && (statusFilter === "all" || request.status === statusFilter);
    });
  }, [data.requests, search, statusFilter]);
  const filteredEngineers = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("ru");
    return data.engineers.filter((engineer) => {
      const matchesSearch = !term || [engineer.name, engineer.external_code]
        .some((value) => value.toLocaleLowerCase("ru").includes(term));
      return matchesSearch && (!availableOnly || engineer.status !== "unavailable");
    });
  }, [availableOnly, data.engineers, search]);

  const selectRequest = (requestId: string) => {
    const request = data.requests.find((item) => item.id === requestId);
    setSelectedRequestId(requestId);
    setSelectedEngineerId(request?.engineer_id ?? null);
    void planner.loadDetailedRoute(request?.engineer_id ?? null);
  };

  const selectEngineer = (engineerId: string) => {
    setSelectedEngineerId(engineerId);
    setSelectedRequestId(null);
    void planner.loadDetailedRoute(engineerId);
  };

  const counts = {
    active: data.requests.filter((item) => item.status === "IN_PROGRESS").length,
    enRoute: data.requests.filter((item) => item.status === "EN_ROUTE").length,
    overdue: data.requests.filter((item) => item.status === "OVERDUE").length,
    done: data.requests.filter((item) => item.status === "COMPLETED").length,
  };

  return (
    <div className="dashboard-page">
      <div className="page-heading compact-heading">
        <div>
          <span className="eyebrow">Оперативный контроль</span>
          <h1>Рабочий день</h1>
          <p>План <strong>{data.plans.find((plan) => plan.id === data.activePlanId)?.code ?? "—"}</strong> · создан {formatTime(data.plans.find((plan) => plan.id === data.activePlanId)?.created_at)}</p>
        </div>
        <button className="button primary" disabled={!canOperate} title={!canOperate ? "Нужен утверждённый план на текущий день" : undefined} onClick={() => setUrgentOpen(true)}><Plus size={17} /> Новая заявка</button>
      </div>

      <section className="kpi-grid day-kpis">
        <article><span className="kpi-icon yellow"><TimerIcon size={21} weight="duotone" /></span><div><b>{counts.active}</b><span>В работе</span></div><em>сейчас</em></article>
        <article><span className="kpi-icon violet"><ArrowUpRightIcon size={21} weight="bold" /></span><div><b>{counts.enRoute}</b><span>В пути</span></div><em>по графику</em></article>
        <article className={counts.overdue ? "attention" : ""}><span className="kpi-icon coral"><WarningCircleIcon size={21} weight="duotone" /></span><div><b>{counts.overdue}</b><span>Просрочено</span></div><em>нужно внимание</em></article>
        <article><span className="kpi-icon green"><CheckCircleIcon size={21} weight="duotone" /></span><div><b>{counts.done}<small>/{data.requests.length}</small></b><span>Выполнено</span></div><em>{Math.round(counts.done / data.requests.length * 100)}% дня</em></article>
        <article><span className="kpi-icon blue"><UsersThreeIcon size={21} weight="duotone" /></span><div><b>{data.metrics.engineers_used}<small>/{data.engineers.length}</small></b><span>На линии</span></div><em>{data.metrics.avg_load_percent}% загрузка</em></article>
      </section>

      <section className="operations-grid">
        <aside className="list-panel">
          <div className="segmented-tabs">
            <button className={tab === "requests" ? "active" : ""} onClick={() => setTab("requests")}>Заявки <span>{data.requests.length}</span></button>
            <button className={tab === "engineers" ? "active" : ""} onClick={() => setTab("engineers")}>Инженеры <span>{data.engineers.length}</span></button>
          </div>
          <div className="list-tools">
            <label className="search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={tab === "requests" ? "ID, адрес или район" : "Имя или код"} /></label>
            {tab === "requests" ? (
              <label className="filter-button"><Filter size={15} /><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as RequestStatus | "all")}><option value="all">Все</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            ) : <button className={`filter-button ${availableOnly ? "active" : ""}`} onClick={() => setAvailableOnly((current) => !current)} aria-pressed={availableOnly} title={availableOnly ? "Показать всех инженеров" : "Показать только доступных инженеров"}><SlidersHorizontal size={15} /><span>{availableOnly ? "Доступные" : "Все"}</span></button>}
          </div>

          <div className="scroll-list">
            {tab === "requests" ? filteredRequests.map((request) => (
              <button key={request.id} className={`request-row ${selectedRequestId === request.id ? "selected" : ""}`} onClick={() => selectRequest(request.id)}>
                <span className={`priority-bar priority-${request.priority_rank}`} />
                <div className="request-row-top"><strong>{request.external_id}</strong><StatusPill status={request.status} /></div>
                <p>{request.bk_type} · {request.district}</p>
                <div className="request-row-meta"><span><Clock3 size={13} /> {formatTime(request.window_start)}–{formatTime(request.window_end)}</span><span><MapPin size={13} /> {request.address.split(",").slice(-1)}</span></div>
                {request.engineer_name ? <div className="assigned-mini"><Avatar name={request.engineer_name} small color={data.engineers.find((item) => item.id === request.engineer_id)?.color} />{request.engineer_name}</div> : <div className="unassigned-mini"><AlertTriangle size={13} /> {request.unassigned_reason}</div>}
                <ChevronRight className="row-chevron" size={16} />
              </button>
            )) : filteredEngineers.map((engineer) => (
              <button key={engineer.id} className={`engineer-row ${selectedEngineerId === engineer.id ? "selected" : ""}`} onClick={() => selectEngineer(engineer.id)}>
                <Avatar name={engineer.name} color={engineer.color} />
                <div><strong>{engineer.name}</strong><span>{engineer.external_code} · {transportLabels[engineer.transport]}</span><div className="skill-dots">{engineer.skills.map((skill) => <i key={skill} data-tooltip={skillLabels[skill]} aria-label={`Квалификация: ${skillLabels[skill]}`}><SkillIcon skill={skill} size={12} /></i>)}</div></div>
                <aside><b>{engineer.request_ids.length}</b><span>заявок</span><em>{(engineer.load_percent ?? Math.round(engineer.load_minutes / 480 * 100))}%</em></aside>
              </button>
            ))}
          </div>
        </aside>

        <MapPanel
          requests={data.requests}
          engineers={data.engineers}
          routes={data.routes}
          detailedRoute={planner.detailedRoute}
          selectedRequestId={selectedRequestId}
          selectedEngineerId={selectedEngineerId}
          routeLoading={planner.routeLoading}
          routeError={planner.routeError}
          onSelectRequest={selectRequest}
        />

        <aside className="detail-panel">
          {selectedRequest ? (
            <RequestDetails
              request={selectedRequest}
              engineer={data.engineers.find((item) => item.id === selectedRequest.engineer_id) ?? null}
              onStatus={(status) => void planner.updateRequestStatus(selectedRequest.id, status)}
              canUpdateStatus={false}
              onClose={() => { setSelectedRequestId(null); setSelectedEngineerId(null); void planner.loadDetailedRoute(null); }}
            />
          ) : selectedEngineer ? (
            <EngineerDetails
              engineer={selectedEngineer}
              requests={data.requests.filter((request) => request.engineer_id === selectedEngineer.id)}
              onRequest={selectRequest}
              onClose={() => { setSelectedEngineerId(null); void planner.loadDetailedRoute(null); }}
            />
          ) : (
            <div className="detail-placeholder"><MapPin size={24} /><h3>Выберите объект</h3><p>Нажмите на заявку, инженера или точку на карте.</p></div>
          )}
        </aside>
      </section>

      {urgentOpen ? <UrgentRequestModal onClose={() => setUrgentOpen(false)} onSubmit={async (payload) => { await planner.createUrgentRequest(payload); setUrgentOpen(false); }} date={data.planningDate} /> : null}
    </div>
  );
}

function RequestDetails({ request, engineer, onStatus, onClose, canUpdateStatus }: {
  request: PlannerController["data"]["requests"][number];
  engineer: PlannerController["data"]["engineers"][number] | null;
  onStatus: (status: RequestStatus) => void;
  canUpdateStatus: boolean;
  onClose: () => void;
}) {
  return (
    <div className="details-content">
      <div className="details-head"><div><span>Заявка</span><h2>{request.external_id}</h2></div><button className="icon-button" onClick={onClose}><X size={17} /></button></div>
      <div className="details-status"><StatusPill status={request.status} /><span className={`priority-label p${request.priority_rank}`}>Приоритет {request.priority_rank}</span></div>
      <div className="details-block"><label>Адрес</label><p>{request.address}</p><small>{request.district}</small></div>
      <div className="detail-two"><div><label>Окно</label><strong>{formatTime(request.window_start)}–{formatTime(request.window_end)}</strong></div><div><label>Норматив</label><strong>{request.full_normative_minutes} мин</strong></div></div>
      <div className="details-block"><label>Тип работ</label><div className="skill-line"><SkillIcon skill={request.required_skill} /> <strong>{request.bk_type}</strong><span>{request.hd_type}</span></div></div>
      {engineer ? (
        <div className="details-block assigned-card"><label>Исполнитель</label><div><Avatar name={engineer.name} color={engineer.color} /><p><strong>{engineer.name}</strong><span><TransportIcon transport={engineer.transport} /> {transportLabels[engineer.transport]}</span></p><em>{formatTime(request.arrival_at)}</em></div></div>
      ) : <div className="warning-card"><AlertTriangle size={17} /><div><strong>Не назначена</strong><span>{request.unassigned_reason}</span></div></div>}
      <div className="explanation-card"><span className="explanation-icon">i</span><div><strong>Почему так</strong><p>{request.explanation}</p></div></div>
      <div className="details-block status-control"><label>Статус заявки</label><select disabled={!canUpdateStatus} title={!canUpdateStatus ? "Backend пока не предоставляет изменение фактического статуса" : undefined} value={request.status} onChange={(event) => onStatus(event.target.value as RequestStatus)}>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{!canUpdateStatus ? <small>Изменение фактического статуса пока не поддерживается API.</small> : null}</div>
      <div className="timeline-mini">{canUpdateStatus ? <><span className="done"><i />Заявка поступила<em>07:31</em></span><span className={request.engineer_id ? "done" : ""}><i />Назначена в план<em>08:12</em></span></> : null}<span className={request.status === "COMPLETED" ? "done" : "current"}><i />{statusLabels[request.status]}<em>{request.arrival_at ? `План ${formatTime(request.arrival_at)}` : ""}</em></span></div>
    </div>
  );
}

function EngineerDetails({ engineer, requests, onRequest, onClose }: {
  engineer: PlannerController["data"]["engineers"][number];
  requests: PlannerController["data"]["requests"];
  onRequest: (requestId: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="details-content engineer-details">
      <div className="details-head"><div><span>Инженер</span><h2>{engineer.external_code}</h2></div><button className="icon-button" onClick={onClose}><X size={17} /></button></div>
      <div className="engineer-profile"><Avatar name={engineer.name} color={engineer.color} /><div><h3>{engineer.name}</h3><span><TransportIcon transport={engineer.transport} /> {transportLabels[engineer.transport]}</span></div><i className={`availability ${engineer.status}`} /></div>
      <div className="skill-chips">{engineer.skills.map((skill) => <span key={skill}><SkillIcon skill={skill} />{skillLabels[skill]}</span>)}</div>
      <div className="detail-three"><div><b>{requests.length}</b><span>заявок</span></div><div><b>{formatDistance(engineer.distance_meters)}</b><span>маршрут</span></div><div><b>{(engineer.load_percent ?? Math.round(engineer.load_minutes / 480 * 100))}%</b><span>загрузка</span></div></div>
      <div className="load-bar"><i style={{ width: `${Math.min(100, engineer.load_percent ?? engineer.load_minutes / 4.8)}%`, background: engineer.color }} /></div>
      <div className="route-list"><label>Маршрут на день</label>{requests.map((request, index) => <button key={request.id} onClick={() => onRequest(request.id)}><span className="route-index" style={{ borderColor: engineer.color }}>{index + 1}</span><div><strong>{formatTime(request.arrival_at ?? request.window_start)} · {request.external_id}</strong><span>{request.address}</span></div><StatusPill status={request.status} /></button>)}</div>
    </div>
  );
}

function UrgentRequestModal({ onClose, onSubmit, date }: { onClose: () => void; onSubmit: (payload: Record<string, unknown>) => Promise<void>; date: string }) {
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ external_id: String(Date.now()).slice(-9), address: "Москва, ", district: "ЮВАО", start: "15:00", end: "17:00" });
  const [formError, setFormError] = useState<string | null>(null);
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form className="modal-card urgent-modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={async (event) => { event.preventDefault(); if (form.end <= form.start) { setFormError("Конец окна должен быть позже начала"); return; } setSaving(true); setFormError(null); try { await onSubmit({ external_id: Number(form.external_id), address: form.address, district: form.district, window_start: `${date}T${form.start}:00`, window_end: `${date}T${form.end}:00` }); } catch (error) { setFormError(error instanceof Error ? error.message : "Не удалось создать заявку"); } finally { setSaving(false); } }}>
        <div className="modal-head"><span className="modal-icon coral"><Siren size={20} /></span><div><h2>Новая срочная заявка</h2><p>После сохранения backend пересчитает план.</p></div><button type="button" className="icon-button" onClick={onClose}><X size={18} /></button></div>
        <div className="form-grid"><label><span>ID заявки</span><input required type="number" min="1" value={form.external_id} onChange={(event) => setForm({ ...form, external_id: event.target.value })} /></label><label><span>Район</span><select value={form.district} onChange={(event) => setForm({ ...form, district: event.target.value })}><option>ЮВАО</option><option>ВАО</option><option>ЮАО</option></select></label><label className="wide"><span>Адрес</span><input required value={form.address} onChange={(event) => setForm({ ...form, address: event.target.value })} /></label><label><span>Начало окна</span><input type="time" value={form.start} onChange={(event) => setForm({ ...form, start: event.target.value })} /></label><label><span>Конец окна</span><input type="time" value={form.end} onChange={(event) => setForm({ ...form, end: event.target.value })} /></label></div>
        <div className="constraint-note"><UserRoundCheck size={17} /><span>Требования: навык «Авария», автомобиль, норматив 100 минут (80 минут работы и 20 минут дороги).</span></div>
        {formError ? <p className="form-error" role="alert">{formError}</p> : null}<div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Отмена</button><button className="button primary" disabled={saving}>{saving ? "Сохраняем…" : "Создать и пересчитать"}</button></div>
      </form>
    </div>
  );
}
