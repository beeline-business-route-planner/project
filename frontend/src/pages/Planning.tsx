import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Download,
  FileSpreadsheet,
  GitCompareArrows,
  History,
  PencilLine,
  Play,
  RotateCcw,
  Route,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  UserRoundX,
  UsersRound,
  X,
} from "lucide-react";
import type { PlanSummary } from "../api/types";
import type { PlannerController } from "../hooks/usePlanner";
import {
  Avatar,
  PlanStatusPill,
  StatusPill,
  formatDateTime,
  formatDistance,
  formatTime,
} from "../components/ui";

type PlanningView = "schedule" | "changes";

export function Planning({ planner }: { planner: PlannerController }) {
  const { data } = planner;
  const [selectedPlanId, setSelectedPlanId] = useState(data.activePlanId);
  const [view, setView] = useState<PlanningView>("schedule");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualRequestId, setManualRequestId] = useState<string | undefined>();
  const [eventOpen, setEventOpen] = useState(false);
  const [eventInitialAction, setEventInitialAction] = useState<"engineer_unavailable" | "urgent_request">("engineer_unavailable");
  const inputRef = useRef<HTMLInputElement>(null);
  const selectedPlan = data.plans.find((plan) => plan.id === selectedPlanId) ?? data.plans[0];
  const isDraft = selectedPlan?.status === "draft";
  const explicitDemo = (import.meta.env.VITE_DEMO_MODE ?? "auto") === "true";
  const canEditManually = false;
  const canOperate = planner.source === "api";
  const canPlanToday = canOperate && data.planningDate === moscowNow().date;
  const actionError = (error: unknown) => planner.showNotice(error instanceof Error ? error.message : "Действие не удалось");

  useEffect(() => {
    if (data.plans.some((plan) => plan.id === selectedPlanId)) return;
    setSelectedPlanId(data.activePlanId);
  }, [data.activePlanId, data.plans, selectedPlanId]);

  const visiblePlans = useMemo(() => data.plans, [data.plans]);
  const unassigned = data.requests.filter((request) => !request.engineer_id && request.status !== "CANCELLED");

  const upload = async () => {
    if (files.length !== 2) {
      planner.showNotice("Выберите ровно два Excel-файла одного округа: заявки и инженеры");
      return;
    }
    if (files.some((file) => !file.name.toLowerCase().endsWith(".xlsx") || file.size === 0 || file.size > 10_000_000)) {
      planner.showNotice("Нужны непустые файлы XLSX размером до 10 МБ каждый");
      return;
    }
    setBusy(true);
    try {
      await planner.importDataset(files);
      setFiles([]);
      if (inputRef.current) inputRef.current.value = "";
    } catch (error) { actionError(error); } finally { setBusy(false); }
  };

  const calculate = async (replan: boolean) => {
    setBusy(true);
    try {
      const planId = await planner.runPlanning(replan);
      setSelectedPlanId(planId);
      setView(replan ? "changes" : "schedule");
    } catch (error) { actionError(error); } finally { setBusy(false); }
  };

  const openManual = (requestId?: string) => {
    setManualRequestId(requestId);
    setManualOpen(true);
  };

  return (
    <div className="planning-page">
      <div className="page-heading">
        <div><span className="eyebrow">Сценарии и назначения</span><h1>Планирование</h1><p>Загрузите данные, проверьте ограничения и утвердите лучший вариант.</p></div>
        <div className="heading-actions"><button className="button secondary" disabled={!canPlanToday} title={!canPlanToday ? "События доступны только для сегодняшнего плана при подключённом API" : undefined} onClick={() => { setEventInitialAction("engineer_unavailable"); setEventOpen(true); }}><CalendarClock size={17} /> Новое событие</button><button className="button primary" disabled={!canPlanToday} title={!canPlanToday ? "Новая заявка доступна только для сегодняшнего плана при подключённом API" : undefined} onClick={() => { setEventInitialAction("urgent_request"); setEventOpen(true); }}><Sparkles size={17} /> Новая заявка</button></div>
      </div>
      {canOperate && !canPlanToday ? <p className="planning-day-notice">Выбран архивный день {data.planningDate}. Его можно просмотреть и скачать, но события и пересчёт API принимает только для сегодняшнего плана. Для нового дня загрузите пару актуальных XLSX.</p> : null}

      <div className="planning-layout">
        <aside className="plans-rail">
          <div className="rail-heading"><div><History size={16} /><strong>История планов</strong></div><span>{visiblePlans.length}</span></div>
          <div className="plan-list">
            {visiblePlans.map((plan) => (
              <button key={plan.id} disabled={busy || (planner.source === "demo" && plan.id !== data.activePlanId)} title={planner.source === "demo" && plan.id !== data.activePlanId ? "Детали версии доступны при подключении backend" : undefined} className={selectedPlanId === plan.id ? "selected" : ""} onClick={() => { setBusy(true); void planner.openPlan(plan.id).then(() => { setSelectedPlanId(plan.id); setView(plan.status === "draft" ? "changes" : "schedule"); }).catch(actionError).finally(() => setBusy(false)); }}>
                <span className={`plan-node ${plan.status}`}><CircleDot size={13} /></span>
                <div><strong>{plan.code}</strong><span>{formatDateTime(plan.created_at)}</span><small>{plan.assigned_count} из {plan.requests_count} назначено</small></div>
                <PlanStatusPill status={plan.status} />
              </button>
            ))}
          </div>
          <div className="rail-tip"><ShieldCheck size={18} /><div><strong>Версионность включена</strong><p>Новый расчёт сохраняется отдельной версией. Утверждённая версия не меняется.</p></div></div>
        </aside>

        <div className="planning-workspace">
          <section className="import-strip">
            <div className="import-copy"><span className="section-number">01</span><div><h2>Исходные данные</h2><p>Пара XLSX одного округа: заявки и инженеры</p></div></div>
            <input ref={inputRef} hidden type="file" multiple accept=".xlsx" onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
            <button className={`file-drop ${files.length ? "has-file" : ""}`} disabled={explicitDemo} title={explicitDemo ? "Импорт требует backend" : undefined} onClick={() => inputRef.current?.click()}>
              {files.length ? <><span className="file-icon ready"><FileSpreadsheet size={18} /></span><div><strong>{files.map((file) => file.name).join(" + ")}</strong><small>{files.length === 2 ? "2 файла выбраны · проверьте, что они относятся к одному округу" : `Выбрано ${files.length}: нужно ровно 2`}</small></div>{files.length === 2 ? <CheckCircle2 size={19} className="success-icon" /> : <AlertTriangle size={19} />}</> : <><span className="file-icon"><UploadCloud size={19} /></span><div><strong>Выбрать два Excel-файла</strong><small>Заявки + инженеры · XLSX до 10 МБ каждый</small></div><ChevronRight size={17} /></>}
            </button>
            {files.length ? <button className="button secondary small" disabled={busy || files.length !== 2} onClick={() => void upload()}>{busy ? "Загрузка…" : "Загрузить"}</button> : null}
          </section>

          <section className="plan-canvas">
            <div className="plan-toolbar">
              <div>
                <div className="plan-title-line"><span className="section-number">02</span><h2>{selectedPlan?.code ?? "Новый план"}</h2>{selectedPlan ? <PlanStatusPill status={selectedPlan.status} /> : null}</div>
                <p>{selectedPlan ? `Создан ${formatDateTime(selectedPlan.created_at)} · ${planner.source === "api" ? "данные backend" : "демонстрационные данные"}` : "Данные ещё не загружены"}</p>
              </div>
              <div className="plan-actions">
                <button className="button ghost" disabled={!canEditManually} title={!canEditManually ? "Backend не предоставляет ручное редактирование назначений" : undefined} onClick={() => openManual()}><PencilLine size={16} /> Изменить вручную</button>
                <button className="button ghost" disabled={busy || !canPlanToday || !data.activePlanId} title={!canPlanToday ? "Пересчёт доступен только для сегодняшнего плана" : undefined} onClick={() => void calculate(true)}><RotateCcw size={16} /> Пересчитать</button>
                <button className="button ghost" disabled={!canOperate || !selectedPlan} onClick={() => { void planner.downloadReport("xlsx", selectedPlan?.id).catch(actionError); }}><Download size={16} /> Скачать XLSX</button>
                {isDraft ? <><button className="button secondary" disabled={busy || !canOperate} onClick={() => { setBusy(true); void planner.rejectPlan(selectedPlan).catch(actionError).finally(() => setBusy(false)); }}><X size={16} /> Отклонить</button><button className="button primary" disabled={busy || !canPlanToday} title={!canPlanToday ? "Утвердить можно только сегодняшний план" : undefined} onClick={() => { setBusy(true); void planner.approvePlan(selectedPlan).catch(actionError).finally(() => setBusy(false)); }}><Check size={16} /> Утвердить план</button></> : null}
              </div>
            </div>

            <div className="plan-metrics">
              <article><span><UsersRound size={17} /></span><div><b>{data.metrics.engineers_used}</b><small>инженеров</small></div></article>
              <article><span><Route size={17} /></span><div><b>{formatDistance(data.metrics.distance_meters)}</b><small>общий пробег</small></div></article>
              <article><span><CheckCircle2 size={17} /></span><div><b>{data.metrics.assigned}</b><small>назначено</small></div></article>
              <article className="warning"><span><AlertTriangle size={17} /></span><div><b>{data.metrics.unassigned}</b><small>без назначения</small></div></article>
              <article><span><Clock3 size={17} /></span><div><b>{data.metrics.avg_load_percent}%</b><small>средняя загрузка</small></div></article>
            </div>

            {isDraft ? (
              <div className="view-tabs"><button className={view === "schedule" ? "active" : ""} onClick={() => setView("schedule")}><Route size={15} /> Новый маршрут</button><button className={view === "changes" ? "active" : ""} onClick={() => setView("changes")}><GitCompareArrows size={15} /> Изменения <em>{data.diff.length}</em></button></div>
            ) : null}

            {view === "changes" && isDraft ? <PlanDiff planner={planner} /> : <Schedule planner={planner} onEditRequest={canEditManually ? openManual : undefined} />}

            {unassigned.length ? (
              <div className="unassigned-section"><div className="unassigned-title"><span><UserRoundX size={17} /></span><div><strong>Не назначены</strong><small>Причина видна для каждой заявки</small></div><em>{unassigned.length}</em></div>{unassigned.map((request) => <div className="unassigned-row" key={request.id}><span className={`priority-badge priority-${request.priority_rank}`}>{request.priority_rank}</span><div><strong>{request.external_id} · {request.bk_type}</strong><span>{request.address}</span></div><p><AlertTriangle size={14} />{request.unassigned_reason}</p><button className="button ghost small" disabled={!canEditManually} title={!canEditManually ? "Ручное назначение недоступно в API" : undefined} onClick={() => openManual(request.id)}>Назначить</button></div>)}</div>
            ) : null}
          </section>
        </div>
      </div>

      {manualOpen ? <ManualChangeModal planner={planner} initialRequestId={manualRequestId} onClose={() => setManualOpen(false)} /> : null}
      {eventOpen ? <DayEventModal planner={planner} initialAction={eventInitialAction} onClose={() => setEventOpen(false)} /> : null}
    </div>
  );
}

function Schedule({ planner, onEditRequest }: { planner: PlannerController; onEditRequest?: (requestId: string) => void }) {
  const { data } = planner;
  return (
    <div className="schedule-board">
      <div className="schedule-scale"><span>Инженер</span>{[8, 10, 12, 14, 16, 18].map((hour) => <i key={hour}>{hour}:00</i>)}</div>
      {data.engineers.filter((engineer) => engineer.request_ids.length).map((engineer) => {
        const requests = data.requests.filter((request) => request.engineer_id === engineer.id);
        return (
          <div className="schedule-row" key={engineer.id}>
            <div className="schedule-engineer"><Avatar name={engineer.name} color={engineer.color} small /><div><strong>{engineer.name}</strong><span>{Math.round(engineer.load_minutes / 480 * 100)}% · {formatDistance(engineer.distance_meters)}</span></div></div>
            <div className="timeline-track">
              {[1, 2, 3, 4, 5].map((line) => <i className="grid-line" key={line} style={{ left: `${line * 16.667}%` }} />)}
              {requests.map((request) => {
                const planned = request.arrival_at ?? request.window_start;
                const start = new Date(planned).getHours() + new Date(planned).getMinutes() / 60;
                const left = Math.max(0, (start - 8) / 10 * 100);
                const width = Math.max(8, request.full_normative_minutes / 600 * 100);
                return <button key={request.id} disabled={!onEditRequest} className={`timeline-job priority-${request.priority_rank}`} style={{ left: `${left}%`, width: `${width}%`, borderColor: engineer.color }} title={`${request.external_id}: ${request.address}${onEditRequest ? ". Нажмите для редактирования." : ""}`} onClick={() => onEditRequest?.(request.id)}><strong>{request.external_id.replace("BK-", "")}</strong><span>{formatTime(planned)}</span></button>;
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PlanDiff({ planner }: { planner: PlannerController }) {
  const { data } = planner;
  const draft = data.plans.find((plan) => plan.status === "draft");
  const base = data.plans.find((plan) => plan.id === draft?.base_plan_id) ?? data.plans.find((plan) => plan.status === "approved");
  return (
    <div className="diff-board">
      <div className="diff-summary"><div><GitCompareArrows size={18} /><span>Сравнение с <strong>{base?.code ?? "базовым планом"}</strong></span></div><div className="diff-legend"><span><i className="new" />Новая</span><span><i className="changed" />Изменена</span><span><i className="removed" />Удалена</span></div></div>
      <div className="diff-table"><div className="diff-header"><span>Заявка</span><span>Было</span><span /><span>Стало</span><span>Что изменилось</span></div>{data.diff.map((item) => <div className={`diff-row state-${item.state}`} key={item.request_id}><span><strong>{item.external_id}</strong><small>{item.state === "new" ? "Новая заявка" : "Переназначение"}</small></span><span><b>{item.old_engineer ?? "Не назначена"}</b><small>{formatTime(item.old_start)}</small></span><span><ArrowRight size={16} /></span><span><b>{item.new_engineer ?? "Не назначена"}</b><small>{formatTime(item.new_start)}</small></span><span>{item.changes.map((change) => <em key={change}>{change === "engineer" ? "Исполнитель" : "Время"}</em>)}</span></div>)}</div>
      <div className="diff-impact"><CheckCircle2 size={17} /><div><strong>Изменения версии</strong><span>Проверьте назначения и причины неназначенных заявок перед утверждением.</span></div></div>
    </div>
  );
}

function ManualChangeModal({ planner, initialRequestId, onClose }: { planner: PlannerController; initialRequestId?: string; onClose: () => void }) {
  const candidates = planner.data.requests.filter((request) => request.status !== "COMPLETED" && request.status !== "CANCELLED");
  const [requestId, setRequestId] = useState(candidates.some((request) => request.id === initialRequestId) ? initialRequestId ?? "" : candidates[0]?.id ?? "");
  const [engineerId, setEngineerId] = useState(planner.data.engineers[0]?.id ?? "");
  const [start, setStart] = useState("15:30");
  const [saving, setSaving] = useState(false);
  return (
    <div className="modal-backdrop" onMouseDown={onClose}><form className="modal-card" onMouseDown={(event) => event.stopPropagation()} onSubmit={async (event) => { event.preventDefault(); setSaving(true); await planner.manualChange(requestId, engineerId, `${planner.data.planningDate}T${start}:00+03:00`); setSaving(false); onClose(); }}><div className="modal-head"><span className="modal-icon violet"><PencilLine size={20} /></span><div><h2>Ручное изменение</h2><p>Будет создан новый черновик, активный план не изменится.</p></div><button type="button" className="icon-button" onClick={onClose}><X size={18} /></button></div><div className="form-grid"><label className="wide"><span>Заявка</span><select value={requestId} onChange={(event) => setRequestId(event.target.value)}>{candidates.map((request) => <option key={request.id} value={request.id}>{request.external_id} · {request.address}</option>)}</select></label><label><span>Инженер</span><select value={engineerId} onChange={(event) => setEngineerId(event.target.value)}>{planner.data.engineers.filter((engineer) => engineer.status !== "unavailable").map((engineer) => <option key={engineer.id} value={engineer.id}>{engineer.name}</option>)}</select></label><label><span>Начало работ</span><input type="time" value={start} onChange={(event) => setStart(event.target.value)} /></label></div><div className="constraint-note"><ShieldCheck size={17} /><span>Backend повторно проверит квалификацию, окно и ресурс.</span></div><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Отмена</button><button className="button primary" disabled={saving}>{saving ? "Сохраняем…" : "Сохранить в черновик"}</button></div></form></div>
  );
}

type EventAction = "engineer_unavailable" | "engineer_available" | "request_cancelled" | "urgent_request";

function moscowNow() {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date()).map((part) => [part.type, part.value]));
  return { date: `${parts.year}-${parts.month}-${parts.day}`, minutes: Number(parts.hour) * 60 + Number(parts.minute) };
}

function eventWindow(date: string) {
  const now = moscowNow();
  if (date !== now.date) return { start: "09:00", end: "11:00" };
  const start = Math.min(23 * 60, Math.ceil((now.minutes + 10) / 15) * 15);
  const end = Math.min(23 * 60 + 59, start + 120);
  const format = (minutes: number) => `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  return { start: format(start), end: format(end) };
}

function DayEventModal({ planner, initialAction, onClose }: { planner: PlannerController; initialAction: EventAction; onClose: () => void }) {
  const [eventType, setEventType] = useState<EventAction>(initialAction);
  const [engineerId, setEngineerId] = useState(planner.data.engineers[0]?.id ?? "");
  const [requestId, setRequestId] = useState(planner.data.requests.find((request) => request.status !== "CANCELLED")?.id ?? "");
  const [requestType, setRequestType] = useState<"global_problem" | "connection">("global_problem");
  const [district, setDistrict] = useState(planner.data.scenarioId === "vostok" ? "ВАО" : planner.data.scenarioId === "yugotsentr" ? "ЮАО" : "ЮВАО");
  const [address, setAddress] = useState("Москва, ");
  const [window, setWindow] = useState(() => eventWindow(planner.data.planningDate));
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const isRequestEvent = eventType === "request_cancelled" || eventType === "urgent_request";
  const eligibleEngineers = planner.data.engineers.filter((engineer) => eventType === "engineer_available" ? engineer.status === "unavailable" : engineer.status !== "unavailable");
  const eventEngineerId = eligibleEngineers.find((engineer) => engineer.id === engineerId)?.id ?? eligibleEngineers[0]?.id ?? "";
  const cancellableRequests = planner.data.requests.filter((request) => !["CANCELLED", "IN_PROGRESS", "COMPLETED"].includes(request.status));
  const eventRequestId = cancellableRequests.find((request) => request.id === requestId)?.id ?? cancellableRequests[0]?.id ?? "";
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);
    if (eventType === "urgent_request") {
      const now = moscowNow();
      if (window.end <= window.start) { setFormError("Конец окна должен быть позже начала."); return; }
      if (planner.data.planningDate < now.date || (planner.data.planningDate === now.date && Number(window.end.slice(0, 2)) * 60 + Number(window.end.slice(3)) <= now.minutes)) {
        setFormError("Окно заявки уже закончилось. Выберите день с действующим планом и будущее время."); return;
      }
    }
    setSaving(true);
    try {
      if (eventType === "urgent_request") {
        await planner.createUrgentRequest({ type_bk: requestType, district, address: address.trim(), window_start: `${planner.data.planningDate}T${window.start}:00`, window_end: `${planner.data.planningDate}T${window.end}:00` });
      } else {
        await planner.createDayEvent(eventType, isRequestEvent ? { request_id: eventRequestId } : { engineer_id: eventEngineerId });
      }
      onClose();
    } catch (error) { setFormError(error instanceof Error ? error.message : "Не удалось сохранить событие"); }
    finally { setSaving(false); }
  };
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form className="modal-card event-modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => void submit(event)}>
        <div className="modal-head"><span className="modal-icon coral"><CalendarClock size={20} /></span><div><h2>Новое событие</h2><p>После сохранения бэкенд создаст новый вариант плана.</p></div><button type="button" className="icon-button" onClick={onClose} aria-label="Закрыть"><X size={18} /></button></div>
        <div className="event-categories" role="group" aria-label="Кого касается событие">
          <button type="button" className={!isRequestEvent ? "active" : ""} onClick={() => setEventType("engineer_unavailable")}>Инженер</button>
          <button type="button" className={isRequestEvent ? "active" : ""} onClick={() => setEventType("urgent_request")}>Заявка</button>
        </div>
        <div className="form-grid">
          <label className="wide"><span>Что произошло</span><select value={eventType} onChange={(event) => setEventType(event.target.value as EventAction)}>
            {isRequestEvent ? <><option value="urgent_request">Добавилась заявка</option><option value="request_cancelled">Заявка отменена</option></> : <><option value="engineer_unavailable">Инженер выбыл</option><option value="engineer_available">Инженер вернулся</option></>}
          </select></label>
          {eventType === "urgent_request" ? <>
            <label><span>Тип заявки</span><select value={requestType} onChange={(event) => setRequestType(event.target.value as "global_problem" | "connection")}><option value="global_problem">Авария</option><option value="connection">Подключение</option></select></label>
            <label><span>Район</span><input required value={district} onChange={(event) => setDistrict(event.target.value)} /></label>
            <label className="wide"><span>Адрес</span><input required value={address} onChange={(event) => setAddress(event.target.value)} /></label>
            <label><span>Начало окна</span><input required type="time" value={window.start} onChange={(event) => setWindow({ ...window, start: event.target.value })} /></label>
            <label><span>Конец окна</span><input required type="time" value={window.end} onChange={(event) => setWindow({ ...window, end: event.target.value })} /></label>
            <p className="event-form-note">День: {planner.data.planningDate}. Номер заявки создаст система. Текущий API принимает здесь аварию и подключение.</p>
          </> : eventType === "request_cancelled" ? <label className="wide"><span>Какую заявку отменить</span><select value={eventRequestId} onChange={(event) => setRequestId(event.target.value)}>{cancellableRequests.map((request) => <option key={request.id} value={request.id}>{request.external_id} · {request.address}</option>)}</select>{!cancellableRequests.length ? <small>Нет заявок, которые можно отменить.</small> : null}</label> : <label className="wide"><span>Инженер</span><select value={eventEngineerId} onChange={(event) => setEngineerId(event.target.value)}>{eligibleEngineers.map((engineer) => <option key={engineer.id} value={engineer.id}>{engineer.name}</option>)}</select>{!eligibleEngineers.length ? <small>Нет инженеров для выбранного события.</small> : null}</label>}
        </div>
        {formError ? <p className="form-error" role="alert">{formError}</p> : null}
        <div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Отмена</button><button className="button primary" disabled={saving || (eventType === "request_cancelled" ? !eventRequestId : eventType === "urgent_request" ? !address.trim() || !district.trim() : !eventEngineerId)}><Play size={16} />{saving ? "Пересчитываем…" : "Создать и пересчитать"}</button></div>
      </form>
    </div>
  );
}
