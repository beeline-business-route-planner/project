import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowDownToLine, ArrowRight, Clock3, FileDown, MapPin, Route, Siren, UsersRound } from "lucide-react";
import { backend } from "../api/services";
import type { BaselineComparison, Engineer, RequestItem } from "../api/types";
import { baselineFromPlan, type PlannerController } from "../hooks/usePlanner";
import { PlanStatusPill, formatDateTime, formatDistance, formatShift, formatTime, statusLabels } from "../components/ui";

const hoursLabel = (minutes: number) => {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h ? `${h} ч${m ? ` ${m} мин` : ""}` : `${m} мин`;
};
const kmLabel = (km: number) => `${km.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} км`;
const plural = (n: number, one: string, few: string, many: string) => {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
};
const isLate = (request: RequestItem) =>
  Boolean(request.engineer_id && request.planned_start && new Date(request.planned_start) > new Date(request.window_end));

export function Journal({ planner, onOpenRequest }: { planner: PlannerController; onOpenRequest: (requestId: string) => void }) {
  const { data } = planner;
  const [baseline, setBaseline] = useState<BaselineComparison | null>(null);
  const [baselineState, setBaselineState] = useState<"loading" | "ready" | "none">("loading");

  // The spec compares the initial plan of the day with the baseline algorithm (п. 2.3, §7).
  const initialPlan = data.plans.find((plan) => plan.kind === "initial" && plan.status !== "rejected")
    ?? data.plans.find((plan) => plan.kind === "initial");
  useEffect(() => {
    if (planner.source !== "api" || !initialPlan) { setBaseline(null); setBaselineState("none"); return; }
    let cancelled = false;
    setBaselineState("loading");
    backend.plan(initialPlan.id)
      .then((plan) => { if (!cancelled) { const comparison = baselineFromPlan(plan); setBaseline(comparison); setBaselineState(comparison ? "ready" : "none"); } })
      .catch(() => { if (!cancelled) { setBaseline(null); setBaselineState("none"); } });
    return () => { cancelled = true; };
  }, [initialPlan?.id, planner.source]);

  const active = data.requests.filter((request) => request.status !== "CANCELLED");
  const assigned = active.filter((request) => request.engineer_id);
  const unassigned = active.filter((request) => !request.engineer_id);
  const late = assigned.filter(isLate);
  const urgent = active.filter((request) => request.priority_rank === 1);
  const urgentOnTime = urgent.filter((request) => request.engineer_id && !isLate(request));
  const coverage = active.length ? Math.round(assigned.length / active.length * 100) : 0;
  const workMinutes = data.metrics.work_minutes ?? 0;
  const travelMinutes = data.metrics.travel_minutes ?? 0;
  const travelShare = workMinutes + travelMinutes ? Math.round(travelMinutes / (workMinutes + travelMinutes) * 100) : 0;
  const activePlan = data.plans.find((plan) => plan.id === data.activePlanId);

  const exportPlansCsv = () => {
    const quote = (value: string | number) => `"${String(value).replaceAll('"', '""')}"`;
    const rows = [
      ["Версия", "Создан", "Статус", "Назначено", "Всего заявок", "Пробег, км"],
      ...data.plans.map((plan) => [plan.title, formatDateTime(plan.created_at), plan.status, plan.assigned_count, plan.requests_count, plan.distance_meters == null ? "" : (plan.distance_meters / 1000).toFixed(1)]),
    ];
    const csv = `﻿${rows.map((row) => row.map(quote).join(";")).join("\r\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `versions-${data.planningDate}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="journal-page analytics-page">
      <div className="page-heading">
        <div><span className="eyebrow">Результаты дня</span><h1>Аналитика</h1><p>{activePlan ? `По рабочему плану «${activePlan.title}»` : "Рабочего плана пока нет"} · {data.planningDate}</p></div>
        <div className="heading-actions">
          <button className="button secondary" onClick={exportPlansCsv}><ArrowDownToLine size={16} /> Версии CSV</button>
          <button className="button primary" disabled={planner.source !== "api"} title={planner.source !== "api" ? "Доступно после подключения backend" : "PDF-отчёт по дню, архив ZIP"} onClick={() => void planner.downloadReport("pdf")}><FileDown size={17} /> Отчёт дня</button>
        </div>
      </div>

      {/* 1. The headline and the numbers a dispatcher reports upward. */}
      <section className="an-summary">
        <article className="an-hero">
          <small>Заявок назначено</small>
          <b>{coverage}%</b>
          <span>{assigned.length} из {active.length}{unassigned.length ? ` · ${unassigned.length} без исполнителя` : " · все распределены"}</span>
          <div className="an-meter" role="img" aria-label={`Назначено ${coverage}%`}><i style={{ width: `${coverage}%` }} /></div>
        </article>
        <StatTile icon={<UsersRound size={17} />} label="Бригад в работе" value={`${data.metrics.engineers_used}`} note={data.metrics.available_engineers ? `из ${data.metrics.available_engineers} доступных` : "задействовано"} />
        <StatTile icon={<Route size={17} />} label="Пробег" value={formatDistance(data.metrics.distance_meters)} note={data.metrics.engineers_used ? `≈ ${kmLabel(data.metrics.distance_meters / 1000 / data.metrics.engineers_used)} на бригаду` : "—"} />
        <StatTile icon={<Clock3 size={17} />} label="Полезная загрузка" value={`${data.metrics.avg_load_percent}%`} note={data.metrics.max_load_percent != null ? `от ${data.metrics.min_load_percent}% до ${data.metrics.max_load_percent}% по бригадам` : "работа и дорога от смены"} />
        <StatTile icon={<Route size={17} />} label="В дороге" value={hoursLabel(travelMinutes)} note={`${travelShare}% рабочего времени бригад`} />
        <StatTile icon={<Siren size={17} />} label="Срочные вовремя" value={urgent.length ? `${urgentOnTime.length} из ${urgent.length}` : "—"} note={urgent.length ? (urgentOnTime.length === urgent.length ? "все в своём окне" : `${urgent.length - urgentOnTime.length} под риском`) : "срочных нет"} tone={urgent.length && urgentOnTime.length < urgent.length ? "bad" : undefined} />
        <StatTile icon={<AlertTriangle size={17} />} label="Опоздания" value={`${late.length}`} note={late.length ? `${plural(late.length, "заявка начнётся", "заявки начнутся", "заявок начнутся")} позже окна` : "все начнутся в окне"} tone={late.length ? "bad" : "good"} />
      </section>

      {/* 2. Required by the spec: initial plan vs baseline, crews and mileage. */}
      <section className="an-card">
        <div className="an-card-head"><div><h2>Сравнение с базовым вариантом</h2><p>Обязательные метрики ТЗ для первичного плана дня: базовый алгоритм назначает заявки по порядку поступления первому подходящему инженеру.</p></div></div>
        {baselineState === "ready" && baseline ? <BaselineRows comparison={baseline} /> : <p className="an-empty">{baselineState === "loading" ? "Загружаем первичный план…" : "Сравнение появится, когда будет рассчитан первичный план дня."}</p>}
      </section>

      {/* 3. Where the shift goes, crew by crew; mileage per crew is required by the spec. */}
      <CrewTime engineers={data.engineers} requests={data.requests} />

      <div className="an-grid">
        {/* 4. What needs the dispatcher now. */}
        <section className="an-card">
          <div className="an-card-head"><div><h2>Требует внимания</h2><p>Нажмите на заявку, чтобы открыть её на карте.</p></div></div>
          <AttentionList unassigned={unassigned} late={late} onOpenRequest={onOpenRequest} />
        </section>

        {/* 5. Composition and progress of the day. */}
        <section className="an-card">
          <div className="an-card-head"><div><h2>Заявки дня</h2><p>Состав по типам и ход выполнения.</p></div></div>
          <BarList title="По типу" rows={countBy(active, (request) => request.bk_type)} total={active.length} />
          <BarList title="По статусу" rows={countBy(data.requests, (request) => statusLabels[request.status])} total={data.requests.length} />
        </section>
      </div>

      {/* 6. How the plan evolved during the day. */}
      <section className="an-card">
        <div className="an-card-head"><div><h2>Версии дня</h2><p>Каждый расчёт и решение по нему. Изменения каждой версии открываются в «Планировании».</p></div></div>
        <div className="an-table" role="table">
          <div className="an-tr an-th" role="row"><span>Версия</span><span>Статус</span><span>Назначено</span><span>Пробег</span><span>Δ пробега</span></div>
          {data.plans.map((plan, index) => {
            const previous = data.plans.slice(index + 1).find((item) => item.status !== "rejected");
            const delta = previous?.distance_meters != null && plan.distance_meters != null ? plan.distance_meters - previous.distance_meters : null;
            return (
              <div className="an-tr" role="row" key={plan.id}>
                <span><strong>{plan.title}</strong><small>{formatDateTime(plan.created_at)}{plan.is_current ? " · текущий" : ""}</small></span>
                <span><PlanStatusPill status={plan.status} /></span>
                <span>{plan.assigned_count} из {plan.requests_count}</span>
                <span>{plan.distance_meters == null ? "—" : formatDistance(plan.distance_meters)}</span>
                <span className={delta == null || Math.abs(delta) < 50 ? "" : delta < 0 ? "an-good" : "an-bad"}>{delta == null ? "—" : Math.abs(delta) < 50 ? "без изменений" : `${delta > 0 ? "+" : "−"}${formatDistance(Math.abs(delta))}`}</span>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function StatTile({ icon, label, value, note, tone }: { icon: React.ReactNode; label: string; value: string; note: string; tone?: "good" | "bad" }) {
  return (
    <article className={`an-tile ${tone ? `is-${tone}` : ""}`}>
      <small><span>{icon}</span>{label}</small>
      <b>{value}</b>
      <em>{note}</em>
    </article>
  );
}

function BaselineRows({ comparison }: { comparison: BaselineComparison }) {
  const rows = [
    { label: "Задействовано исполнителей", plan: comparison.plan.engineers_used, base: comparison.baseline.engineers_used, format: (v: number) => `${v}`, lowerIsBetter: true },
    { label: "Суммарный пробег", plan: comparison.plan.distance_km, base: comparison.baseline.distance_km, format: kmLabel, lowerIsBetter: true },
    { label: "Назначено заявок", plan: comparison.plan.assigned, base: comparison.baseline.assigned, format: (v: number) => `${v}`, lowerIsBetter: false },
  ];
  return (
    <div className="an-baseline">
      <div className="an-legend"><span><i className="plan" />Наш план</span><span><i className="base" />Базовый вариант</span></div>
      {rows.map((row) => {
        const max = Math.max(row.plan, row.base, 1);
        const delta = row.plan - row.base;
        const better = delta === 0 ? null : (delta < 0) === row.lowerIsBetter;
        const percent = row.base ? Math.round(Math.abs(delta) / row.base * 100) : 0;
        return (
          <div className="an-bl-row" key={row.label}>
            <span className="an-bl-label">{row.label}</span>
            <div className="an-bl-bars">
              <div><i className="plan" style={{ width: `${row.plan / max * 100}%` }} /><b>{row.format(row.plan)}</b></div>
              <div><i className="base" style={{ width: `${row.base / max * 100}%` }} /><b>{row.format(row.base)}</b></div>
            </div>
            <span className={`an-bl-delta ${better == null ? "" : better ? "an-good" : "an-bad"}`}>{delta === 0 ? "как у базового" : `${delta > 0 ? "+" : "−"}${row.format(Math.abs(delta))}${percent ? ` (${percent}%)` : ""} ${better ? "лучше" : "хуже"}`}</span>
          </div>
        );
      })}
    </div>
  );
}

function CrewTime({ engineers, requests }: { engineers: Engineer[]; requests: RequestItem[] }) {
  const [hover, setHover] = useState<{ engineer: Engineer; rect: DOMRect } | null>(null);
  const rows = useMemo(() => engineers
    .filter((engineer) => engineer.status !== "unavailable" || engineer.request_ids.length)
    .map((engineer) => {
      const work = Math.max(0, Math.min(100, engineer.work_percent));
      const travel = Math.max(0, Math.min(100 - work, engineer.load_percent - engineer.work_percent));
      return { engineer, work, travel, free: Math.max(0, 100 - work - travel), jobs: requests.filter((request) => request.engineer_id === engineer.id).length };
    })
    .sort((left, right) => right.engineer.load_percent - left.engineer.load_percent), [engineers, requests]);
  return (
    <section className="an-card">
      <div className="an-card-head">
        <div><h2>Как бригады тратят смену</h2><p>Доля смены на работу и дорогу. Справа — полезная загрузка, число заявок и пробег бригады.</p></div>
        <div className="an-legend"><span><i className="work" />Работа</span><span><i className="travel" />Дорога</span><span><i className="free" />Свободно</span></div>
      </div>
      <div className="an-crews">
        {rows.map(({ engineer, work, travel, free, jobs }) => (
          <div
            className="an-crew"
            key={engineer.id}
            tabIndex={0}
            aria-label={`${engineer.name}: работа ${Math.round(work)}%, дорога ${Math.round(travel)}%, свободно ${Math.round(free)}%, ${jobs} заявок, ${formatDistance(engineer.distance_meters)}`}
            onMouseEnter={(event) => setHover({ engineer, rect: event.currentTarget.getBoundingClientRect() })}
            onMouseLeave={() => setHover(null)}
            onFocus={(event) => setHover({ engineer, rect: event.currentTarget.getBoundingClientRect() })}
            onBlur={() => setHover(null)}
          >
            <span className="an-crew-name"><i style={{ background: engineer.color }} /><strong>{engineer.name}</strong><small>{formatShift(engineer)}</small></span>
            <div className="an-crew-bar">
              {work > 0 ? <i className="work" style={{ width: `${work}%` }} /> : null}
              {travel > 0 ? <i className="travel" style={{ width: `${travel}%` }} /> : null}
              {free > 0 ? <i className="free" style={{ width: `${free}%` }} /> : null}
            </div>
            <span className="an-crew-value"><b>{Math.round(engineer.load_percent)}%</b><small>{jobs} {plural(jobs, "заявка", "заявки", "заявок")} · {formatDistance(engineer.distance_meters)}</small></span>
          </div>
        ))}
      </div>
      {hover ? <CrewCard {...hover} rows={rows} /> : null}
    </section>
  );
}

function CrewCard({ engineer, rect, rows }: { engineer: Engineer; rect: DOMRect; rows: Array<{ engineer: Engineer; work: number; travel: number; free: number; jobs: number }> }) {
  const row = rows.find((item) => item.engineer.id === engineer.id);
  if (!row) return null;
  const width = 260;
  const left = Math.min(Math.max(12, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 12);
  return (
    <div className="stop-card" role="tooltip" style={{ left, width, bottom: window.innerHeight - rect.top + 8 }}>
      <div className="stop-card-head"><strong>{engineer.name}</strong></div>
      <p className="stop-card-type">Смена {formatShift(engineer)}</p>
      <dl>
        <dt>Работа</dt><dd><i style={{ background: "var(--an-work)" }} />{Math.round(row.work)}% смены</dd>
        <dt>Дорога</dt><dd><i style={{ background: "var(--an-travel)" }} />{Math.round(row.travel)}% смены</dd>
        <dt>Свободно</dt><dd><i style={{ background: "var(--an-free)" }} />{Math.round(row.free)}% смены</dd>
        <dt>Заявок</dt><dd>{row.jobs}</dd>
        <dt>Пробег</dt><dd>{formatDistance(engineer.distance_meters)}</dd>
      </dl>
    </div>
  );
}

function AttentionList({ unassigned, late, onOpenRequest }: { unassigned: RequestItem[]; late: RequestItem[]; onOpenRequest: (requestId: string) => void }) {
  const byReason = countBy(unassigned, (request) => request.unassigned_reason ?? "Причина не указана");
  if (!unassigned.length && !late.length) return <p className="an-empty an-ok">Все заявки назначены и начнутся в своём окне.</p>;
  const item = (request: RequestItem, meta: string) => (
    <button key={request.id} type="button" className="an-item" onClick={() => onOpenRequest(request.id)}>
      <span className={`priority-badge priority-${request.priority_rank}`}>{request.priority_rank}</span>
      <span><strong>{request.external_id} · {request.bk_type}</strong><small>{request.address}</small></span>
      <em>{meta}</em>
      <MapPin size={15} />
    </button>
  );
  return (
    <div className="an-attention">
      {byReason.map(([reason, count]) => (
        <div key={reason} className="an-group">
          <h3><AlertTriangle size={14} />{reason}<b>{count}</b></h3>
          {unassigned.filter((request) => (request.unassigned_reason ?? "Причина не указана") === reason).map((request) => item(request, `окно ${formatTime(request.window_start)}–${formatTime(request.window_end)}`))}
        </div>
      ))}
      {late.length ? (
        <div className="an-group">
          <h3><Clock3 size={14} />Начнутся позже окна<b>{late.length}</b></h3>
          {late.map((request) => item(request, `окно до ${formatTime(request.window_end)}, начало ${formatTime(request.planned_start)}`))}
        </div>
      ) : null}
      <p className="an-hint"><ArrowRight size={13} />Изменить назначения можно событием дня в «Планировании».</p>
    </div>
  );
}

function countBy<T>(items: T[], key: (item: T) => string): Array<[string, number]> {
  const counts = new Map<string, number>();
  items.forEach((item) => counts.set(key(item), (counts.get(key(item)) ?? 0) + 1));
  return [...counts.entries()].sort((left, right) => right[1] - left[1]);
}

function BarList({ title, rows, total }: { title: string; rows: Array<[string, number]>; total: number }) {
  const max = Math.max(1, ...rows.map(([, count]) => count));
  return (
    <div className="an-barlist">
      <h3>{title}</h3>
      {rows.map(([label, count]) => (
        <div key={label} className="an-barrow">
          <span>{label}</span>
          <div><i style={{ width: `${count / max * 100}%` }} /></div>
          <b>{count}<small>{total ? ` · ${Math.round(count / total * 100)}%` : ""}</small></b>
        </div>
      ))}
    </div>
  );
}
