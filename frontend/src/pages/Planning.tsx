import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  Check,
  CheckCircle2,
  CircleDot,
  Clock3,
  Download,
  FileSpreadsheet,
  GitCompareArrows,
  History,
  Lock,
  MapPin,
  Play,
  RotateCcw,
  Route,
  Trash2,
  UploadCloud,
  UserRoundCheck,
  UserRoundX,
  UsersRound,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import type { Engineer, PlanSummary, RequestItem } from "../api/types";
import type { PlannerController } from "../hooks/usePlanner";
import {
  Avatar,
  PlanStatusPill,
  StatusPill,
  formatDateTime,
  formatDistance,
  formatShift,
  formatTime,
} from "../components/ui";

type PlanningView = "schedule" | "changes";
type EventAction = "engineer_unavailable" | "engineer_available" | "request_cancelled" | "urgent_request";

const dayActions: Array<{ action: EventAction; label: string; hint: string; icon: typeof Zap }> = [
  { action: "urgent_request", label: "Срочная заявка", hint: "Авария или подключение вне плана", icon: Zap },
  { action: "engineer_unavailable", label: "Инженер выбыл", hint: "Его заявки перераспределятся", icon: UserRoundX },
  { action: "engineer_available", label: "Инженер вернулся", hint: "Снова получит заявки", icon: UserRoundCheck },
  { action: "request_cancelled", label: "Заявка отменена", hint: "Уйдёт из маршрута", icon: XCircle },
];

export function Planning({ planner, onOpenRequest }: { planner: PlannerController; onOpenRequest: (requestId: string) => void }) {
  const { data } = planner;
  const [selectedPlanId, setSelectedPlanId] = useState(data.activePlanId);
  const [view, setView] = useState<PlanningView>("schedule");
  const [busy, setBusy] = useState(false);
  const [eventAction, setEventAction] = useState<EventAction | null>(null);
  const versionsRef = useRef<HTMLElement>(null);
  const selectedPlan = data.plans.find((plan) => plan.id === selectedPlanId) ?? data.plans[0];
  const isDraft = selectedPlan?.status === "draft";
  const canOperate = planner.source === "api";
  const canPlanToday = canOperate && data.planningDate === moscowNow().date;
  const actionError = (error: unknown) => planner.showNotice(error instanceof Error ? error.message : "Действие не удалось");

  useEffect(() => {
    if (data.plans.some((plan) => plan.id === selectedPlanId)) return;
    setSelectedPlanId(data.activePlanId);
  }, [data.activePlanId, data.plans, selectedPlanId]);

  const unassigned = data.requests.filter((request) => !request.engineer_id && request.status !== "CANCELLED");

  const openPlan = (plan: PlanSummary, scroll = false) => {
    setBusy(true);
    void planner.openPlan(plan.id)
      .then(() => {
        setSelectedPlanId(plan.id);
        setView(plan.status === "draft" && plan.kind !== "initial" ? "changes" : "schedule");
        if (scroll) versionsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      })
      .catch(actionError)
      .finally(() => setBusy(false));
  };

  const replan = async () => {
    setBusy(true);
    try {
      const planId = await planner.runPlanning(true);
      setSelectedPlanId(planId);
      setView("changes");
      versionsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) { actionError(error); } finally { setBusy(false); }
  };

  return (
    <div className="planning-page">
      <div className="page-heading">
        <div><span className="eyebrow">Сценарии и назначения</span><h1>Планирование</h1><p>Загрузка дня, изменения по ходу дня и версии плана округа.</p></div>
      </div>

      <DayPanel planner={planner} busy={busy} canPlanToday={canPlanToday} onEvent={setEventAction} onReplan={() => void replan()} onOpenPlan={(plan) => openPlan(plan, true)} />

      <section className="versions-block" ref={versionsRef}>
        <div className="block-heading"><h2>Версии плана</h2><p>Каждый расчёт — отдельная версия. Рабочей становится только утверждённая.</p></div>
        <div className="planning-layout">
          <aside className="plans-rail">
            <div className="rail-heading"><div><History size={16} /><strong>История</strong></div><span>{data.plans.length}</span></div>
            <div className="plan-list">
              {data.plans.map((plan) => (
                <button key={plan.id} disabled={busy || (planner.source === "demo" && plan.id !== data.activePlanId)} title={planner.source === "demo" && plan.id !== data.activePlanId ? "Детали версии доступны при подключении backend" : undefined} className={selectedPlanId === plan.id ? "selected" : ""} onClick={() => openPlan(plan)}>
                  <span className={`plan-node ${plan.status}`}><CircleDot size={13} /></span>
                  <div><strong>{plan.title}</strong><span>{formatDateTime(plan.created_at)}{plan.is_current ? " · текущий" : ""}</span><small>{plan.assigned_count} из {plan.requests_count} назначено</small></div>
                  <PlanStatusPill status={plan.status} />
                </button>
              ))}
              {!data.plans.length ? <p className="rail-empty">Версий пока нет. Загрузите день выше.</p> : null}
            </div>
          </aside>

          <section className="plan-canvas">
            <div className="plan-toolbar">
              <div>
                <div className="plan-title-line"><h2>{selectedPlan?.title ?? "Плана пока нет"}</h2>{selectedPlan ? <PlanStatusPill status={selectedPlan.status} /> : null}{selectedPlan?.is_current ? <span className="current-chip">Текущий</span> : null}</div>
                <p>{selectedPlan ? `Рассчитан ${formatDateTime(selectedPlan.created_at)}${selectedPlan.approved_at ? ` · утверждён ${formatDateTime(selectedPlan.approved_at)}` : ""}` : "Загрузите пару XLSX округа, чтобы рассчитать первый план."}</p>
              </div>
              <div className="plan-actions">
                <button className="button ghost" disabled={!canOperate || !selectedPlan} onClick={() => { void planner.downloadReport("xlsx", selectedPlan?.id).catch(actionError); }}><Download size={16} /> XLSX</button>
                {isDraft ? <><button className="button secondary" disabled={busy || !canOperate} onClick={() => { setBusy(true); void planner.rejectPlan(selectedPlan).catch(actionError).finally(() => setBusy(false)); }}><X size={16} /> Отклонить</button><button className="button primary" disabled={busy || !canPlanToday} title={!canPlanToday ? "Утвердить можно только сегодняшний план" : undefined} onClick={() => { setBusy(true); void planner.approvePlan(selectedPlan).catch(actionError).finally(() => setBusy(false)); }}><Check size={16} /> Утвердить</button></> : null}
              </div>
            </div>
            {isDraft ? <div className="decision-note"><AlertTriangle size={15} />Версия ожидает решения и пока не влияет на работу бригад.</div> : null}

            <div className="plan-metrics">
              <article><span><UsersRound size={17} /></span><div><b>{data.metrics.engineers_used}</b><small>бригад в работе</small></div></article>
              <article><span><Route size={17} /></span><div><b>{formatDistance(data.metrics.distance_meters)}</b><small>общий пробег</small></div></article>
              <article><span><CheckCircle2 size={17} /></span><div><b>{data.metrics.assigned}</b><small>назначено</small></div></article>
              <article className="warning"><span><AlertTriangle size={17} /></span><div><b>{data.metrics.unassigned}</b><small>без назначения</small></div></article>
              <article><span><Clock3 size={17} /></span><div><b>{data.metrics.avg_load_percent}%</b><small>средняя загрузка</small></div></article>
            </div>

            {isDraft && selectedPlan?.kind !== "initial" ? (
              <div className="view-tabs"><button className={view === "schedule" ? "active" : ""} onClick={() => setView("schedule")}><Route size={15} /> Маршруты</button><button className={view === "changes" ? "active" : ""} onClick={() => setView("changes")}><GitCompareArrows size={15} /> Изменения <em>{data.diff.length}</em></button></div>
            ) : null}

            {view === "changes" && isDraft ? <PlanDiff planner={planner} /> : <DaySchedule engineers={data.engineers} requests={data.requests} isToday={data.planningDate === moscowNow().date} onOpenRequest={onOpenRequest} />}

            {unassigned.length ? (
              <div className="unassigned-section"><div className="unassigned-title"><span><UserRoundX size={17} /></span><div><strong>Не назначены</strong><small>Причина видна для каждой заявки</small></div><em>{unassigned.length}</em></div>{unassigned.map((request) => <div className="unassigned-row" key={request.id}><span className={`priority-badge priority-${request.priority_rank}`}>{request.priority_rank}</span><div><strong>{request.external_id} · {request.bk_type}</strong><span>{request.address}</span></div><p><AlertTriangle size={14} />{request.unassigned_reason}</p></div>)}</div>
            ) : null}
          </section>
        </div>
      </section>

      {eventAction ? <DayEventModal planner={planner} initialAction={eventAction} onClose={() => setEventAction(null)} /> : null}
    </div>
  );
}

/* "День округа": only what the user case allows right now — upload a day,
   or change an approved day (events / replan), or just view an archived day. */
function DayPanel({ planner, busy, canPlanToday, onEvent, onReplan, onOpenPlan }: {
  planner: PlannerController;
  busy: boolean;
  canPlanToday: boolean;
  onEvent: (action: EventAction) => void;
  onReplan: () => void;
  onOpenPlan: (plan: PlanSummary) => void;
}) {
  const { data } = planner;
  const explicitDemo = (import.meta.env.VITE_DEMO_MODE ?? "auto") === "true";
  const approved = data.plans.some((plan) => plan.status === "approved" || plan.status === "superseded");
  const pending = data.plans.filter((plan) => plan.status === "draft");
  const pendingEvent = pending.find((plan) => plan.kind === "event_replan");
  const pendingInitial = pending.find((plan) => plan.kind === "initial");
  const isArchive = planner.source === "api" && !canPlanToday;

  if (isArchive || explicitDemo) {
    return (
      <section className="day-panel is-muted">
        <div className="block-heading"><h2>День округа</h2><p>{isArchive ? `Архивный день ${data.planningDate}: план можно посмотреть и скачать, изменения не принимаются.` : "Демонстрационный режим: загрузка и события требуют backend."}</p></div>
      </section>
    );
  }

  if (!approved) {
    return (
      <section className="day-panel">
        <div className="block-heading"><h2>День округа</h2><p>Рабочий план на сегодня ещё не утверждён. Загрузите пару XLSX — backend рассчитает первичный план, его нужно будет утвердить.</p></div>
        {pendingInitial ? <PendingNote plan={pendingInitial} text="Уже рассчитан первичный план и ждёт решения. Можно утвердить его или загрузить файлы заново." onOpen={onOpenPlan} /> : null}
        <UploadPanel planner={planner} />
      </section>
    );
  }

  return (
    <section className="day-panel">
      <div className="block-heading">
        <h2>День округа</h2>
        <p>Что-то изменилось по ходу дня — выберите событие. Backend рассчитает новую версию, рабочий план сменится только после утверждения.</p>
      </div>
      {pendingEvent ? <PendingNote plan={pendingEvent} text="Пока событие ждёт решения, новое создать нельзя — утвердите или отклоните его." onOpen={onOpenPlan} /> : null}
      <div className="day-actions">
        {dayActions.map(({ action, label, hint, icon: Icon }) => (
          <button key={action} type="button" className={`day-action ${action}`} disabled={busy || Boolean(pendingEvent)} onClick={() => onEvent(action)}>
            <span className="day-action-icon"><Icon size={19} /></span>
            <strong>{label}</strong>
            <small>{hint}</small>
          </button>
        ))}
        <button type="button" className="day-action replan" disabled={busy} onClick={onReplan}>
          <span className="day-action-icon"><RotateCcw size={19} /></span>
          <strong>{busy ? "Считаем…" : "Пересчитать"}</strong>
          <small>Без события, по текущим статусам</small>
        </button>
      </div>
      <p className="day-lock"><Lock size={13} />Загрузка XLSX закрыта: первичный план дня уже утверждён.</p>
    </section>
  );
}

function PendingNote({ plan, text, onOpen }: { plan: PlanSummary; text: string; onOpen: (plan: PlanSummary) => void }) {
  return (
    <div className="pending-note">
      <AlertTriangle size={17} />
      <div><strong>Ожидает решения: {plan.title}</strong><span>{text}</span></div>
      <button type="button" className="button secondary small" onClick={() => onOpen(plan)}>Открыть версию <ArrowRight size={14} /></button>
    </div>
  );
}

/* Day schedule: one row per crew, real travel / wait / work intervals from the plan. */

// Wide enough that a 40-minute job still fits its time range and number.
const HOUR_PX = 176;
const ENGINEER_COL_PX = 210;

function minuteOfDay(value: string | null | undefined) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.getHours() * 60 + date.getMinutes();
}

interface StopBar {
  request: RequestItem;
  travelFrom: number | null;
  arrival: number;
  start: number;
  finish: number;
}

function stopBars(requests: RequestItem[]): StopBar[] {
  return requests.flatMap((request) => {
    const start = minuteOfDay(request.planned_start ?? request.arrival_at);
    if (start == null) return [];
    const arrival = minuteOfDay(request.arrival_at) ?? start;
    const finish = minuteOfDay(request.planned_finish) ?? start + request.service_minutes;
    const travel = request.travel_minutes ?? 0;
    return [{ request, travelFrom: travel > 0 ? arrival - travel : null, arrival, start, finish: Math.max(finish, start + 1) }];
  }).sort((left, right) => left.start - right.start);
}

function DaySchedule({ engineers, requests, isToday, onOpenRequest }: { engineers: Engineer[]; requests: RequestItem[]; isToday: boolean; onOpenRequest: (requestId: string) => void }) {
  const boardRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ bar: StopBar; engineer: Engineer; rect: DOMRect } | null>(null);
  const rows = useMemo(() => engineers
    .map((engineer) => ({ engineer, bars: stopBars(requests.filter((request) => request.engineer_id === engineer.id)) }))
    .filter((row) => row.bars.length), [engineers, requests]);

  // The visible day spans every shift and every planned interval, whole hours.
  const [fromHour, toHour] = useMemo(() => {
    const minutes = rows.flatMap(({ engineer, bars }) => [
      minuteOfDay(engineer.shift_start), minuteOfDay(engineer.shift_end),
      ...bars.flatMap((bar) => [bar.travelFrom ?? bar.arrival, bar.finish]),
    ]).filter((value): value is number => value != null);
    if (!minutes.length) return [8, 20];
    return [Math.max(0, Math.floor(Math.min(...minutes) / 60)), Math.min(24, Math.ceil(Math.max(...minutes) / 60))];
  }, [rows]);
  const x = (minute: number) => ((minute - fromHour * 60) / 60) * HOUR_PX;
  const trackWidth = (toHour - fromHour) * HOUR_PX;
  const now = moscowNow().minutes;
  const showNow = isToday && now >= fromHour * 60 && now <= toHour * 60;

  // Open the board at the current time (today) or at the first job.
  useEffect(() => {
    const board = boardRef.current;
    if (!board) return;
    const firstJob = Math.min(...rows.map((row) => row.bars[0].travelFrom ?? row.bars[0].start));
    const focus = showNow ? now - 60 : Number.isFinite(firstJob) ? firstJob - 30 : fromHour * 60;
    board.scrollLeft = Math.max(0, x(focus));
    // Only when the plan (rows) changes, not on every clock tick.
  }, [rows]);

  if (!rows.length) return <div className="day-empty"><Route size={20} /><strong>В этой версии нет маршрутов</strong><span>Назначенные заявки появятся здесь по бригадам.</span></div>;

  return (
    <div className="day-schedule">
      <div className="day-legend">
        <span><i className="work" />Работа</span>
        <span><i className="travel" />Дорога</span>
        <span><i className="wait" />Ожидание окна</span>
        <span><i className="shift" />Смена</span>
        {showNow ? <span><i className="now" />Сейчас</span> : null}
        <em>Наведите на заявку — детали, нажмите — открыть на карте</em>
      </div>
      <div className="day-board" ref={boardRef}>
        <div className="day-grid" style={{ width: ENGINEER_COL_PX + trackWidth, ["--hour" as string]: `${HOUR_PX}px` }}>
          <div className="day-head">
            <div className="day-corner" style={{ width: ENGINEER_COL_PX }}>Бригада</div>
            <div className="day-scale" style={{ width: trackWidth }}>
              {Array.from({ length: toHour - fromHour }, (_, index) => <span key={index} style={{ left: index * HOUR_PX }}>{String(fromHour + index).padStart(2, "0")}:00</span>)}
            </div>
          </div>
          {rows.map(({ engineer, bars }) => {
            const shiftStart = minuteOfDay(engineer.shift_start);
            const shiftEnd = minuteOfDay(engineer.shift_end);
            return (
              <div className="day-row" key={engineer.id}>
                <div className="day-engineer" style={{ width: ENGINEER_COL_PX }}>
                  <Avatar name={engineer.name} color={engineer.color} small />
                  <div><strong>{engineer.name}</strong><span>{formatShift(engineer)} · {Math.round(engineer.load_percent)}%</span></div>
                </div>
                <div className="day-track" style={{ width: trackWidth }}>
                  {shiftStart != null && shiftEnd != null ? <i className="day-shift" style={{ left: x(shiftStart), width: x(shiftEnd) - x(shiftStart) }} /> : null}
                  {bars.map((bar) => {
                    const { request } = bar;
                    const workWidth = x(bar.finish) - x(bar.start);
                    const late = isLate(bar);
                    const show = (target: HTMLElement) => setHover({ bar, engineer, rect: target.getBoundingClientRect() });
                    return (
                      <div key={request.id} className="day-stop">
                        {bar.travelFrom != null ? <i className="day-travel" style={{ left: x(bar.travelFrom), width: x(bar.arrival) - x(bar.travelFrom) }} /> : null}
                        {bar.start > bar.arrival ? <i className="day-wait" style={{ left: x(bar.arrival), width: x(bar.start) - x(bar.arrival) }} /> : null}
                        <button
                          type="button"
                          className={["day-work", `priority-${request.priority_rank}`, request.status === "COMPLETED" ? "is-done" : "", late ? "is-late" : ""].filter(Boolean).join(" ")}
                          style={{ left: x(bar.start), width: workWidth, ["--crew" as string]: engineer.color }}
                          aria-label={`${request.external_id}, ${request.bk_type}, работа ${clock(bar.start)}–${clock(bar.finish)}. Открыть на карте`}
                          onMouseEnter={(event) => show(event.currentTarget)}
                          onMouseLeave={() => setHover(null)}
                          onFocus={(event) => show(event.currentTarget)}
                          onBlur={() => setHover(null)}
                          onClick={() => onOpenRequest(request.id)}
                        >
                          {/* Time first: it is what the dispatcher scans the board for. */}
                          <strong>{workWidth >= 96 ? `${clock(bar.start)}–${clock(bar.finish)}` : clock(bar.start)}</strong>
                          {workWidth >= 72 ? <span>{workWidth >= 150 ? `${request.external_id} · ${request.bk_type}` : request.external_id}</span> : null}
                        </button>
                      </div>
                    );
                  })}
                  {showNow ? <i className="day-now" style={{ left: x(now) }} /> : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {hover ? <StopCard {...hover} /> : null}
    </div>
  );
}

const clock = (minute: number) => `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;

function isLate(bar: StopBar) {
  const windowEnd = minuteOfDay(bar.request.window_end);
  return windowEnd != null && bar.start > windowEnd;
}

// Floating card next to the hovered job; fixed positioning escapes the scroll area.
function StopCard({ bar, engineer, rect }: { bar: StopBar; engineer: Engineer; rect: DOMRect }) {
  const { request } = bar;
  const width = 300;
  const left = Math.min(Math.max(12, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 12);
  const below = rect.top < 260;
  const late = isLate(bar);
  return (
    <div className="stop-card" role="tooltip" style={{ left, width, ...(below ? { top: rect.bottom + 10 } : { bottom: window.innerHeight - rect.top + 10 }) }}>
      <div className="stop-card-head">
        <strong>{request.external_id}</strong>
        <StatusPill status={request.status} />
      </div>
      <p className="stop-card-type">{request.bk_type}{request.hd_type && request.hd_type !== request.bk_type ? ` · ${request.hd_type}` : ""} · приоритет {request.priority_rank}</p>
      <p className="stop-card-address">{request.address}<small>{request.district}</small></p>
      <dl>
        <dt>Окно</dt><dd>{formatTime(request.window_start)}–{formatTime(request.window_end)}</dd>
        {request.travel_minutes ? <><dt>Дорога</dt><dd>{request.travel_minutes} мин · прибытие {clock(bar.arrival)}</dd></> : null}
        {bar.start > bar.arrival ? <><dt>Ожидание</dt><dd>{bar.start - bar.arrival} мин до начала окна</dd></> : null}
        <dt>Работа</dt><dd>{clock(bar.start)}–{clock(bar.finish)} · {bar.finish - bar.start} мин</dd>
        <dt>Бригада</dt><dd><i style={{ background: engineer.color }} />{engineer.name}</dd>
      </dl>
      {late ? <p className="stop-card-warning"><AlertTriangle size={14} />Работа начинается позже окна заявки</p> : null}
      <p className="stop-card-hint"><MapPin size={13} />Нажмите, чтобы открыть на карте</p>
    </div>
  );
}

function PlanDiff({ planner }: { planner: PlannerController }) {
  const { data } = planner;
  const draft = data.plans.find((plan) => plan.status === "draft");
  const base = data.plans.find((plan) => plan.id === draft?.base_plan_id) ?? data.plans.find((plan) => plan.status === "approved");
  const baseName = base ? `«${base.title}»` : "текущим планом";
  const format = (value: number, unit: string) => `${Number.isInteger(value) ? value : value.toFixed(1).replace(".", ",")}${unit}`;
  return (
    <div className="diff-board">
      <div className="diff-summary"><div><GitCompareArrows size={18} /><span>Сравнение с {baseName}</span></div>{data.diff.length ? <div className="diff-legend"><span><i className="new" />Новая</span><span><i className="changed" />Изменена</span><span><i className="removed" />Удалена</span></div> : null}</div>
      {data.diffSummary?.length ? (
        <div className="diff-metrics">
          {data.diffSummary.map((metric) => {
            const good = metric.delta === 0 ? "same" : (metric.delta > 0) === (metric.better === "up") ? "better" : "worse";
            return (
              <div key={metric.key} className={`diff-metric ${good}`}>
                <small>{metric.label}</small>
                <b>{format(metric.after, metric.unit)}</b>
                <span>{metric.delta === 0 ? "без изменений" : `${metric.delta > 0 ? "+" : "−"}${format(Math.abs(metric.delta), metric.unit)} · было ${format(metric.before, metric.unit)}`}</span>
              </div>
            );
          })}
        </div>
      ) : null}
      {data.diff.length ? (
        <div className="diff-table"><div className="diff-header"><span>Заявка</span><span>Было</span><span /><span>Стало</span><span>Что изменилось</span></div>{data.diff.map((item) => <div className={`diff-row state-${item.state}`} key={item.request_id}><span><strong>{item.external_id}</strong><small>{item.state === "new" ? "Новая заявка" : item.state === "removed" ? "Убрана из плана" : "Переназначение"}</small></span><span><b>{item.old_engineer ?? "Не назначена"}</b><small>{formatTime(item.old_start)}</small></span><span><ArrowRight size={16} /></span><span><b>{item.new_engineer ?? "Не назначена"}</b><small>{formatTime(item.new_start)}</small></span><span>{item.changes.map((change) => <em key={change}>{change === "engineer" ? "Исполнитель" : change === "time" || change === "planned_start" ? "Время" : change}</em>)}</span></div>)}</div>
      ) : (
        <div className="diff-empty">
          <CheckCircle2 size={22} />
          <div>
            <strong>Пересчёт ничего не изменил</strong>
            <span>{data.diffCompared ? `Все ${data.diffCompared} заявок остались у тех же бригад в то же время, что и в ${baseName}.` : `Маршруты совпадают с ${baseName}.`} Утверждать эту версию незачем — её можно отклонить, рабочий план останется прежним.</span>
          </div>
        </div>
      )}
    </div>
  );
}

function UploadPanel({ planner }: { planner: PlannerController }) {
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const add = (incoming: FileList | null) => {
    setFormError(null);
    // Picking again adds files; the same name replaces the previous copy.
    setFiles((current) => [...current.filter((file) => !Array.from(incoming ?? []).some((item) => item.name === file.name)), ...Array.from(incoming ?? [])].slice(-2));
  };
  const problem = files.length !== 2
    ? `Нужно 2 файла, выбрано ${files.length}`
    : files.some((file) => !file.name.toLowerCase().endsWith(".xlsx")) ? "Оба файла должны быть в формате XLSX"
      : files.some((file) => file.size === 0 || file.size > 10_000_000) ? "Каждый файл — непустой и до 10 МБ" : null;
  const submit = async () => {
    if (problem) { setFormError(problem); return; }
    setSaving(true);
    try { await planner.importDataset(files); setFiles([]); }
    catch (error) { setFormError(error instanceof Error ? error.message : "Не удалось загрузить файлы"); }
    finally { setSaving(false); }
  };
  return (
    <div className="upload-panel">
      <input ref={inputRef} hidden type="file" multiple accept=".xlsx" onChange={(event) => { add(event.target.files); event.target.value = ""; }} />
      <button
        type="button"
        className={`upload-drop ${dragging ? "is-dragging" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); add(event.dataTransfer.files); }}
      >
        <UploadCloud size={26} />
        <strong>Перетащите сюда два файла: заявки и инженеры</strong>
        <span>или нажмите, чтобы выбрать · XLSX до 10 МБ · округ backend определит сам</span>
      </button>
      <div className="upload-side">
        {files.length ? (
          <ul className="upload-files">
            {files.map((file) => (
              <li key={file.name}><FileSpreadsheet size={17} /><div><strong>{file.name}</strong><small>{(file.size / 1024).toFixed(0)} КБ</small></div><button type="button" className="icon-button" aria-label={`Убрать ${file.name}`} onClick={() => setFiles((current) => current.filter((item) => item !== file))}><Trash2 size={15} /></button></li>
            ))}
          </ul>
        ) : <p className="upload-empty">Файлы не выбраны</p>}
        {formError ? <p className="form-error" role="alert">{formError}</p> : null}
        <button type="button" className="button primary" disabled={saving || files.length !== 2} onClick={() => void submit()}><Play size={16} />{saving ? "Загружаем и считаем…" : "Загрузить и рассчитать"}</button>
      </div>
    </div>
  );
}

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

const eventTitles: Record<EventAction, { title: string; note: string }> = {
  urgent_request: { title: "Срочная заявка", note: "Номер заявки создаст система. Текущий API принимает аварию и подключение." },
  engineer_unavailable: { title: "Инженер выбыл", note: "Его незавершённые заявки перераспределятся между остальными бригадами." },
  engineer_available: { title: "Инженер вернулся", note: "Бригада снова получит заявки при пересчёте." },
  request_cancelled: { title: "Заявка отменена", note: "Заявка уйдёт из маршрута, освободившееся время займут другие." },
};

function DayEventModal({ planner, initialAction, onClose }: { planner: PlannerController; initialAction: EventAction; onClose: () => void }) {
  const eventType = initialAction;
  const [engineerId, setEngineerId] = useState(planner.data.engineers[0]?.id ?? "");
  const [requestId, setRequestId] = useState(planner.data.requests.find((request) => request.status !== "CANCELLED")?.id ?? "");
  const [requestType, setRequestType] = useState<"global_problem" | "connection">("global_problem");
  const [district, setDistrict] = useState(planner.data.scenarioId === "vostok" ? "ВАО" : planner.data.scenarioId === "yugotsentr" ? "ЮАО" : "ЮВАО");
  const [address, setAddress] = useState("Москва, ");
  const [window, setWindow] = useState(() => eventWindow(planner.data.planningDate));
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
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
        setFormError("Окно заявки уже закончилось. Выберите будущее время."); return;
      }
    }
    setSaving(true);
    try {
      if (eventType === "urgent_request") {
        await planner.createUrgentRequest({ type_bk: requestType, district, address: address.trim(), window_start: `${planner.data.planningDate}T${window.start}:00`, window_end: `${planner.data.planningDate}T${window.end}:00` });
      } else {
        await planner.createDayEvent(eventType, eventType === "request_cancelled" ? { request_id: eventRequestId } : { engineer_id: eventEngineerId });
      }
      onClose();
    } catch (error) { setFormError(error instanceof Error ? error.message : "Не удалось сохранить событие"); }
    finally { setSaving(false); }
  };
  const { title, note } = eventTitles[eventType];
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form className="modal-card event-modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => void submit(event)}>
        <div className="modal-head"><span className="modal-icon coral"><CalendarClock size={20} /></span><div><h2>{title}</h2><p>{note} После сохранения backend создаст новую версию плана.</p></div><button type="button" className="icon-button" onClick={onClose} aria-label="Закрыть"><X size={18} /></button></div>
        <div className="form-grid">
          {eventType === "urgent_request" ? <>
            <label><span>Тип заявки</span><select value={requestType} onChange={(event) => setRequestType(event.target.value as "global_problem" | "connection")}><option value="global_problem">Авария</option><option value="connection">Подключение</option></select></label>
            <label><span>Район</span><input required value={district} onChange={(event) => setDistrict(event.target.value)} /></label>
            <label className="wide"><span>Адрес</span><input required value={address} onChange={(event) => setAddress(event.target.value)} /></label>
            <label><span>Начало окна</span><input required type="time" value={window.start} onChange={(event) => setWindow({ ...window, start: event.target.value })} /></label>
            <label><span>Конец окна</span><input required type="time" value={window.end} onChange={(event) => setWindow({ ...window, end: event.target.value })} /></label>
          </> : eventType === "request_cancelled" ? <label className="wide"><span>Какую заявку отменить</span><select value={eventRequestId} onChange={(event) => setRequestId(event.target.value)}>{cancellableRequests.map((request) => <option key={request.id} value={request.id}>{request.external_id} · {request.address}</option>)}</select>{!cancellableRequests.length ? <small>Нет заявок, которые можно отменить.</small> : null}</label> : <label className="wide"><span>Бригада</span><select value={eventEngineerId} onChange={(event) => setEngineerId(event.target.value)}>{eligibleEngineers.map((engineer) => <option key={engineer.id} value={engineer.id}>{engineer.name} · {formatShift(engineer)}</option>)}</select>{!eligibleEngineers.length ? <small>{eventType === "engineer_available" ? "Все бригады и так доступны." : "Нет доступных бригад."}</small> : null}</label>}
        </div>
        {formError ? <p className="form-error" role="alert">{formError}</p> : null}
        <div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Отмена</button><button className="button primary" disabled={saving || (eventType === "request_cancelled" ? !eventRequestId : eventType === "urgent_request" ? !address.trim() || !district.trim() : !eventEngineerId)}><Play size={16} />{saving ? "Пересчитываем…" : "Создать и пересчитать"}</button></div>
      </form>
    </div>
  );
}
