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
  const [selectedPlanId, setSelectedPlanId] = useState(data.plans.find((plan) => plan.status === "draft")?.id ?? data.activePlanId);
  const [view, setView] = useState<PlanningView>("schedule");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualRequestId, setManualRequestId] = useState<string | undefined>();
  const [eventOpen, setEventOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const selectedPlan = data.plans.find((plan) => plan.id === selectedPlanId) ?? data.plans[0];
  const isDraft = selectedPlan?.status === "draft";

  useEffect(() => {
    if (data.plans.some((plan) => plan.id === selectedPlanId)) return;
    setSelectedPlanId(data.plans.find((plan) => plan.status === "draft")?.id ?? data.activePlanId);
  }, [data.activePlanId, data.plans, selectedPlanId]);

  const visiblePlans = useMemo(() => data.plans, [data.plans]);
  const unassigned = data.requests.filter((request) => !request.engineer_id && request.status !== "CANCELLED");

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    try { await planner.importDataset(file); } finally { setBusy(false); }
  };

  const calculate = async (replan: boolean) => {
    setBusy(true);
    try {
      const planId = await planner.runPlanning(replan);
      setSelectedPlanId(planId);
      setView(replan ? "changes" : "schedule");
    } finally { setBusy(false); }
  };

  const openManual = (requestId?: string) => {
    setManualRequestId(requestId);
    setManualOpen(true);
  };

  return (
    <div className="planning-page">
      <div className="page-heading">
        <div><span className="eyebrow">Сценарии и назначения</span><h1>Планирование</h1><p>Загрузите данные, проверьте ограничения и утвердите лучший вариант.</p></div>
        <div className="heading-actions"><button className="button secondary" onClick={() => setEventOpen(true)}><CalendarClock size={17} /> Событие дня</button><button className="button primary" disabled={busy} onClick={() => void calculate(Boolean(data.activePlanId))}><Sparkles size={17} /> {data.activePlanId ? "Перепланировать" : "Сформировать план"}</button></div>
      </div>

      <div className="planning-layout">
        <aside className="plans-rail">
          <div className="rail-heading"><div><History size={16} /><strong>История планов</strong></div><span>{visiblePlans.length}</span></div>
          <div className="plan-list">
            {visiblePlans.map((plan) => (
              <button key={plan.id} className={selectedPlanId === plan.id ? "selected" : ""} onClick={() => { setSelectedPlanId(plan.id); setView(plan.status === "draft" ? "changes" : "schedule"); }}>
                <span className={`plan-node ${plan.status}`}><CircleDot size={13} /></span>
                <div><strong>{plan.code}</strong><span>{formatDateTime(plan.created_at)}</span><small>{plan.assigned_count} из {plan.requests_count} назначено</small></div>
                <PlanStatusPill status={plan.status} />
              </button>
            ))}
          </div>
          <div className="rail-tip"><ShieldCheck size={18} /><div><strong>Версионность включена</strong><p>Ручные правки создают новый план. Утверждённая версия не меняется.</p></div></div>
        </aside>

        <div className="planning-workspace">
          <section className="import-strip">
            <div className="import-copy"><span className="section-number">01</span><div><h2>Исходные данные</h2><p>Excel с заявками и параметрами сценария</p></div></div>
            <input ref={inputRef} hidden type="file" accept=".xlsx,.xls" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            <button className={`file-drop ${file ? "has-file" : ""}`} onClick={() => inputRef.current?.click()}>
              {file ? <><span className="file-icon ready"><FileSpreadsheet size={18} /></span><div><strong>{file.name}</strong><small>{(file.size / 1024).toFixed(0)} КБ · готов к загрузке</small></div><CheckCircle2 size={19} className="success-icon" /></> : <><span className="file-icon"><UploadCloud size={19} /></span><div><strong>Выбрать Excel-файл</strong><small>XLSX, до 10 МБ</small></div><ChevronRight size={17} /></>}
            </button>
            {file ? <button className="button secondary small" disabled={busy} onClick={() => void upload()}>{busy ? "Загрузка…" : "Загрузить"}</button> : null}
          </section>

          <section className="plan-canvas">
            <div className="plan-toolbar">
              <div>
                <div className="plan-title-line"><span className="section-number">02</span><h2>{selectedPlan?.code ?? "Новый план"}</h2>{selectedPlan ? <PlanStatusPill status={selectedPlan.status} /> : null}</div>
                <p>{selectedPlan?.input_version ?? "Данные ещё не загружены"} · расчёт 2,8 с · OSRM</p>
              </div>
              <div className="plan-actions">
                <button className="button ghost" onClick={() => openManual()}><PencilLine size={16} /> Изменить вручную</button>
                <button className="button ghost" onClick={() => void calculate(true)}><RotateCcw size={16} /> Пересчитать</button>
                {isDraft ? <button className="button primary" onClick={() => void planner.approvePlan(selectedPlan)}><Check size={16} /> Утвердить план</button> : null}
              </div>
            </div>

            <div className="plan-metrics">
              <article><span><UsersRound size={17} /></span><div><b>{data.metrics.engineers_used}</b><small>инженеров</small></div></article>
              <article><span><Route size={17} /></span><div><b>{formatDistance(data.metrics.distance_meters)}</b><small>общий пробег</small></div></article>
              <article><span><CheckCircle2 size={17} /></span><div><b>{data.metrics.assigned}</b><small>назначено</small></div></article>
              <article className="warning"><span><AlertTriangle size={17} /></span><div><b>{data.metrics.unassigned}</b><small>без назначения</small></div></article>
              <article><span><Clock3 size={17} /></span><div><b>{data.metrics.on_time_percent}%</b><small>вовремя</small></div></article>
            </div>

            {isDraft ? (
              <div className="view-tabs"><button className={view === "schedule" ? "active" : ""} onClick={() => setView("schedule")}><Route size={15} /> Новый маршрут</button><button className={view === "changes" ? "active" : ""} onClick={() => setView("changes")}><GitCompareArrows size={15} /> Изменения <em>{data.diff.length}</em></button></div>
            ) : null}

            {view === "changes" && isDraft ? <PlanDiff planner={planner} /> : <Schedule planner={planner} onEditRequest={openManual} />}

            {unassigned.length ? (
              <div className="unassigned-section"><div className="unassigned-title"><span><UserRoundX size={17} /></span><div><strong>Не назначены</strong><small>Причина видна для каждой заявки</small></div><em>{unassigned.length}</em></div>{unassigned.map((request) => <div className="unassigned-row" key={request.id}><span className={`priority-badge priority-${request.priority_rank}`}>{request.priority_rank}</span><div><strong>{request.external_id} · {request.bk_type}</strong><span>{request.address}</span></div><p><AlertTriangle size={14} />{request.unassigned_reason}</p><button className="button ghost small" onClick={() => openManual(request.id)}>Назначить</button></div>)}</div>
            ) : null}
          </section>
        </div>
      </div>

      {manualOpen ? <ManualChangeModal planner={planner} initialRequestId={manualRequestId} onClose={() => setManualOpen(false)} /> : null}
      {eventOpen ? <DayEventModal planner={planner} onClose={() => setEventOpen(false)} /> : null}
    </div>
  );
}

function Schedule({ planner, onEditRequest }: { planner: PlannerController; onEditRequest: (requestId: string) => void }) {
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
                const start = new Date(request.window_start).getHours() + new Date(request.window_start).getMinutes() / 60;
                const left = Math.max(0, (start - 8) / 10 * 100);
                const width = Math.max(8, request.full_normative_minutes / 600 * 100);
                return <button key={request.id} className={`timeline-job priority-${request.priority_rank}`} style={{ left: `${left}%`, width: `${width}%`, borderColor: engineer.color }} title={`${request.external_id}: ${request.address}. Нажмите для редактирования.`} onClick={() => onEditRequest(request.id)}><strong>{request.external_id.replace("BK-", "")}</strong><span>{formatTime(request.window_start)}</span></button>;
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
      <div className="diff-impact"><CheckCircle2 size={17} /><div><strong>Все ограничения соблюдены</strong><span>Квалификация, временные окна и ресурсы проверены для нового варианта.</span></div></div>
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

function DayEventModal({ planner, onClose }: { planner: PlannerController; onClose: () => void }) {
  const [eventType, setEventType] = useState("engineer_unavailable");
  const [engineerId, setEngineerId] = useState(planner.data.engineers[0]?.id ?? "");
  const [saving, setSaving] = useState(false);
  return (
    <div className="modal-backdrop" onMouseDown={onClose}><form className="modal-card" onMouseDown={(event) => event.stopPropagation()} onSubmit={async (event) => { event.preventDefault(); setSaving(true); await planner.createDayEvent(eventType, { engineer_id: engineerId }); setSaving(false); onClose(); }}><div className="modal-head"><span className="modal-icon coral"><CalendarClock size={20} /></span><div><h2>Событие рабочего дня</h2><p>Событие станет причиной перепланирования и попадёт в аудит.</p></div><button type="button" className="icon-button" onClick={onClose}><X size={18} /></button></div><div className="form-grid"><label><span>Тип события</span><select value={eventType} onChange={(event) => setEventType(event.target.value)}><option value="engineer_unavailable">Инженер недоступен</option><option value="request_cancelled">Заявка отменена</option><option value="fact_changed">Изменился факт</option><option value="urgent_request">Срочная заявка</option></select></label><label><span>Инженер</span><select value={engineerId} onChange={(event) => setEngineerId(event.target.value)}>{planner.data.engineers.map((engineer) => <option key={engineer.id} value={engineer.id}>{engineer.name}</option>)}</select></label></div><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Отмена</button><button className="button primary" disabled={saving}><Play size={16} />{saving ? "Пересчитываем…" : "Зафиксировать и пересчитать"}</button></div></form></div>
  );
}
