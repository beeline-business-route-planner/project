import { useMemo, useState } from "react";
import {
  ArrowDownToLine,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  FileDown,
  Filter,
  GitCompareArrows,
  History,
  Search,
  UsersRound,
} from "lucide-react";
import type { PlannerController } from "../hooks/usePlanner";
import { PlanStatusPill, formatDateTime, formatDistance } from "../components/ui";

export function Journal({
  planner,
  onOpenComparison,
  view,
}: {
  planner: PlannerController;
  onOpenComparison: (oldPlanId: string, newPlanId: string) => Promise<void>;
  view: "analytics" | "history";
}) {
  const { data } = planner;
  const [query, setQuery] = useState("");
  const [actionFilter, setActionFilter] = useState("all");
  const [typesExpanded, setTypesExpanded] = useState(true);
  const [oldPlanId, setOldPlanId] = useState(data.plans[2]?.id ?? data.plans[0]?.id);
  const [newPlanId, setNewPlanId] = useState(data.activePlanId);
  const filteredAudit = useMemo(() => {
    const term = query.toLocaleLowerCase("ru");
    return data.audit.filter((item) => {
      const matchesTerm = !term || [item.action, item.entity, item.entity_id, item.actor, item.details].some((value) => value.toLocaleLowerCase("ru").includes(term));
      return matchesTerm && (actionFilter === "all" || item.action === actionFilter);
    });
  }, [actionFilter, data.audit, query]);
  const auditActions = useMemo(() => Array.from(new Set(data.audit.map((item) => item.action))), [data.audit]);

  const typeCounts = [
    { label: "Локальные", count: data.requests.filter((item) => item.bk_type === "Локальная" || item.bk_type === "Локальные работы").length, color: "#1964dc" },
    { label: "Подключения", count: data.requests.filter((item) => item.bk_type === "Подключение").length, color: "#ffdb00" },
    { label: "Дозаказы", count: data.requests.filter((item) => item.bk_type === "Дозаказ").length, color: "#bf6400" },
    { label: "Аварии", count: data.requests.filter((item) => item.bk_type === "Авария").length, color: "#ef6b4a" },
  ];
  const maxType = Math.max(1, ...typeCounts.map((item) => item.count));
  const total = data.metrics.assigned + data.metrics.unassigned;
  const coverage = total ? Math.round(data.metrics.assigned / total * 100) : 0;
  const base = data.plans.find((plan) => plan.id === oldPlanId);
  const compared = data.plans.find((plan) => plan.id === newPlanId);
  const assignmentDelta = base && compared ? compared.assigned_count - base.assigned_count : null;
  const mileageDelta = base?.distance_meters != null && compared?.distance_meters != null
    ? compared.distance_meters - base.distance_meters : null;
  const baseCoverage = base?.requests_count ? Math.round(base.assigned_count / base.requests_count * 100) : null;
  const nextCoverage = compared?.requests_count ? Math.round(compared.assigned_count / compared.requests_count * 100) : null;
  const dateLabel = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" }).format(new Date(`${data.planningDate}T12:00:00`));

  const exportPlansCsv = () => {
    const quote = (value: string | number) => `"${String(value).replaceAll('"', '""')}"`;
    const rows = [
      ["Версия", "Создан", "Статус", "Назначено", "Всего заявок", "Пробег, м"],
      ...data.plans.map((plan) => [
        plan.code,
        formatDateTime(plan.created_at),
        plan.status,
        plan.assigned_count,
        plan.requests_count,
        plan.distance_meters ?? "",
      ]),
    ];
    const csv = `\uFEFF${rows.map((row) => row.map(quote).join(";")).join("\r\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `plans-${data.planningDate}.csv`;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="journal-page">
      <div className="page-heading">
        <div><span className="eyebrow">Результаты и трассировка</span><h1>{view === "analytics" ? "Аналитика" : "История версий"}</h1><p>{view === "analytics" ? "Показатели качества и отчёт по рабочему дню." : "Сохранённые планы, сравнение и журнал решений."}</p></div>
        {view === "analytics" ? <div className="heading-actions"><button className="button primary dark" disabled={planner.source !== "api"} title={planner.source !== "api" ? "Доступно после подключения backend" : "Архив PDF-отчётов"} onClick={() => void planner.downloadReport("pdf")}><FileDown size={17} /> Отчёт ZIP</button></div> : null}
      </div>
      {view === "analytics" ? (
        <>
          <section className="analytics-kpis">
            <article><span className="metric-icon violet"><CheckCircle2 size={19} /></span><div><small>Охват заявок</small><b>{coverage}%</b><em>{data.metrics.assigned} из {total} распределены</em></div></article>
            <article><span className="metric-icon yellow"><CircleDot size={19} /></span><div><small>Назначено</small><b>{data.metrics.assigned}</b><em>заявок в плане</em></div></article>
            <article><span className="metric-icon teal"><UsersRound size={19} /></span><div><small>Средняя загрузка</small><b>{data.metrics.avg_load_percent}%</b><em>{data.metrics.engineers_used} инженеров задействовано</em></div></article>
            <article><span className="metric-icon coral"><GitCompareArrows size={19} /></span><div><small>Без назначения</small><b>{data.metrics.unassigned}</b><em>требуют внимания</em></div></article>
            <article><span className="metric-icon blue"><BarChart3 size={19} /></span><div><small>Общий пробег</small><b>{formatDistance(data.metrics.distance_meters)}</b><em>по всем маршрутам</em></div></article>
          </section>

          <div className="analytics-grid">
            <section className="chart-card workload-chart">
              <div className="card-head"><div><h2>Загрузка инженеров</h2><p>Работы + дорога от 8-часовой смены</p></div><span className="chart-badge">План {data.plans.find((plan) => plan.id === data.activePlanId)?.code}</span></div>
              <div className="workload-bars">{data.engineers.map((engineer) => { const percent = Math.round(engineer.load_minutes / 480 * 100); return <div key={engineer.id}><span>{engineer.name}</span><div><i style={{ width: `${Math.min(100, percent)}%`, background: engineer.color }} /></div><b>{percent}%</b></div>; })}</div>
              <div className="chart-axis"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
            </section>

            <section className={`chart-card request-types ${typesExpanded ? "" : "is-collapsed"}`}>
              <div className="card-head"><div><h2>Типы работ</h2><p>{data.requests.length} заявок за день</p></div><button className="icon-button" onClick={() => setTypesExpanded((current) => !current)} aria-expanded={typesExpanded} aria-label={typesExpanded ? "Свернуть типы работ" : "Развернуть типы работ"} title={typesExpanded ? "Свернуть" : "Развернуть"}><ChevronDown size={16} /></button></div>
              {typesExpanded ? <><div className="type-bars">{typeCounts.map((item) => <div key={item.label}><span>{item.label}</span><div><i style={{ width: `${item.count / maxType * 100}%`, background: item.color }} /></div><b>{item.count}</b></div>)}</div>
              <div className="priority-note"><span className="priority-medal">!</span><p><strong>Аварийные работы</strong><small>{typeCounts[3].count} заявок в текущем плане</small></p></div></> : <button className="collapsed-summary" onClick={() => setTypesExpanded(true)}>{typeCounts.map((item) => <span key={item.label}><i style={{ background: item.color }} />{item.label}<b>{item.count}</b></span>)}</button>}
            </section>

            <section className="chart-card coverage-card">
              <div className="card-head"><div><h2>Результат планирования</h2><p>Распределение всех заявок</p></div></div>
              <div className="coverage-summary"><div className="coverage-number"><b>{coverage}%</b><span>заявок распределено</span></div><div className="coverage-track" role="img" aria-label={`${data.metrics.assigned} назначено, ${data.metrics.unassigned} без назначения`}><i style={{ width: `${coverage}%` }} /></div><div className="coverage-breakdown"><div><span className="coverage-dot assigned" /><span>Назначено</span><strong>{data.metrics.assigned}</strong></div><div><span className="coverage-dot unassigned" /><span>Без назначения</span><strong>{data.metrics.unassigned}</strong></div></div></div>
            </section>

          </div>

        </>
      ) : (
        <div className="history-sections">
          <section className="chart-card compare-card">
            <div className="card-head"><div><h2>Сравнить планы</h2><p>Изменения маршрутов и назначений</p></div><GitCompareArrows size={18} /></div>
            <div className="compare-selects"><label><span>Базовый</span><select value={oldPlanId} onChange={(event) => setOldPlanId(event.target.value)}>{data.plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.code}</option>)}</select></label><span className="compare-arrow">→</span><label><span>Новый</span><select value={newPlanId} onChange={(event) => setNewPlanId(event.target.value)}>{data.plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.code}</option>)}</select></label></div>
            <div className="compare-stats"><div><b>{assignmentDelta == null ? "—" : `${assignmentDelta > 0 ? "+" : ""}${assignmentDelta}`}</b><span>назначения</span></div><div><b>{mileageDelta == null ? "—" : `${mileageDelta > 0 ? "+" : ""}${formatDistance(mileageDelta)}`}</b><span>пробег</span></div><div><b>{baseCoverage == null || nextCoverage == null ? "—" : `${nextCoverage - baseCoverage > 0 ? "+" : ""}${nextCoverage - baseCoverage} п.п.`}</b><span>охват</span></div></div>
            <button className="button secondary wide" disabled={planner.source !== "api" || !base || !compared || oldPlanId === newPlanId || compared.base_plan_id !== oldPlanId} onClick={() => void onOpenComparison(oldPlanId, newPlanId)}><GitCompareArrows size={16} /> Открыть изменения</button>
          </section>
          <section className="plans-table-card">
            <div className="card-head"><div><h2>Версии плана</h2><p>Каждый расчёт сохранён и доступен для проверки</p></div><button className="button ghost" onClick={exportPlansCsv}><ArrowDownToLine size={16} /> Экспорт списка</button></div>
            <div className="plans-table"><div className="table-head"><span>Версия</span><span>Создан</span><span>Статус</span><span>Заявки</span><span>Пробег</span><span>Источник</span></div>{data.plans.map((plan) => <div className="table-row" key={plan.id}><span><CircleDot size={14} className={`plan-dot ${plan.status}`} /><strong>{plan.code}</strong></span><span>{formatDateTime(plan.created_at)}</span><span><PlanStatusPill status={plan.status} /></span><span>{plan.assigned_count}/{plan.requests_count}</span><span>{plan.distance_meters == null ? "—" : formatDistance(plan.distance_meters)}</span><span>{planner.source === "api" ? "Backend" : "Демо"}</span></div>)}</div>
          </section>
        <section className="audit-card">
          <div className="audit-tools"><label className="search-field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Действие, объект или автор" /></label><span className="filter-button filter-chip"><CalendarDays size={15} /> {dateLabel}</span><label className="filter-button audit-select"><Filter size={15} /><select value={actionFilter} onChange={(event) => setActionFilter(event.target.value)} aria-label="Фильтр действий"><option value="all">Все действия</option>{auditActions.map((action) => <option key={action} value={action}>{action}</option>)}</select></label></div>
          <div className="audit-list">{filteredAudit.length ? filteredAudit.map((item, index) => <article key={item.id}><span className={`audit-node audit-${index % 4}`}><History size={15} /></span><div className="audit-main"><div><strong>{item.action}</strong><span>{item.entity} · {item.entity_id}</span></div><p>{item.details}</p></div><div className="audit-meta"><strong>{item.actor}</strong><span>{formatDateTime(item.timestamp)}</span></div></article>) : <div className="empty-filter">По выбранным условиям действий не найдено.</div>}</div>
        </section>
        </div>
      )}
    </div>
  );
}
