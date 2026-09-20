import { useMemo, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Clock3,
  FileDown,
  FileSpreadsheet,
  Filter,
  GitCompareArrows,
  History,
  Search,
  TimerReset,
  UsersRound,
} from "lucide-react";
import type { PlannerController } from "../hooks/usePlanner";
import { PlanStatusPill, formatDateTime, formatDistance } from "../components/ui";

export function Journal({
  planner,
  onOpenComparison,
}: {
  planner: PlannerController;
  onOpenComparison: (oldPlanId: string, newPlanId: string) => Promise<void>;
}) {
  const { data } = planner;
  const [tab, setTab] = useState<"analytics" | "audit">("analytics");
  const [query, setQuery] = useState("");
  const [oldPlanId, setOldPlanId] = useState(data.plans[2]?.id ?? data.plans[0]?.id);
  const [newPlanId, setNewPlanId] = useState(data.activePlanId);
  const filteredAudit = useMemo(() => {
    const term = query.toLocaleLowerCase("ru");
    return data.audit.filter((item) => !term || [item.action, item.entity, item.entity_id, item.actor, item.details].some((value) => value.toLocaleLowerCase("ru").includes(term)));
  }, [data.audit, query]);

  const typeCounts = [
    { label: "Локальные", count: data.requests.filter((item) => item.required_skill === "local").length, color: "#6f4cff" },
    { label: "Подключения", count: data.requests.filter((item) => item.required_skill === "connection").length, color: "#ffdb00" },
    { label: "Аварии", count: data.requests.filter((item) => item.required_skill === "emergency").length, color: "#ef6b4a" },
  ];
  const maxType = Math.max(...typeCounts.map((item) => item.count));

  return (
    <div className="journal-page">
      <div className="page-heading">
        <div><span className="eyebrow">Результаты и трассировка</span><h1>Журнал и отчёты</h1><p>История решений, метрики качества и выгрузки по рабочему дню.</p></div>
        <div className="heading-actions"><button className="button secondary" onClick={() => void planner.downloadReport("xlsx")}><FileSpreadsheet size={17} /> XLSX</button><button className="button primary dark" onClick={() => void planner.downloadReport("pdf")}><FileDown size={17} /> PDF-отчёт</button></div>
      </div>

      <div className="journal-tabs"><button className={tab === "analytics" ? "active" : ""} onClick={() => setTab("analytics")}><BarChart3 size={16} /> Аналитика</button><button className={tab === "audit" ? "active" : ""} onClick={() => setTab("audit")}><History size={16} /> История действий <span>{data.audit.length}</span></button></div>

      {tab === "analytics" ? (
        <>
          <section className="analytics-kpis">
            <article><span className="metric-icon violet"><CheckCircle2 size={19} /></span><div><small>Охват заявок</small><b>{Math.round(data.metrics.assigned / (data.metrics.assigned + data.metrics.unassigned) * 100)}%</b><em>+8% к исходному</em></div></article>
            <article><span className="metric-icon yellow"><Clock3 size={19} /></span><div><small>Вовремя</small><b>{data.metrics.on_time_percent}%</b><em>12 из 13 назначенных</em></div></article>
            <article><span className="metric-icon teal"><UsersRound size={19} /></span><div><small>Средняя загрузка</small><b>{data.metrics.avg_load_percent}%</b><em>разброс 18 п.п.</em></div></article>
            <article><span className="metric-icon coral"><Activity size={19} /></span><div><small>Общий пробег</small><b>{formatDistance(data.metrics.distance_meters)}</b><em>−12,4 км к базе</em></div></article>
            <article><span className="metric-icon blue"><TimerReset size={19} /></span><div><small>Время расчёта</small><b>2,8 c</b><em>p95 · 3,2 с</em></div></article>
          </section>

          <div className="analytics-grid">
            <section className="chart-card workload-chart">
              <div className="card-head"><div><h2>Загрузка инженеров</h2><p>Работы + дорога от 8-часовой смены</p></div><span className="chart-badge">План {data.plans.find((plan) => plan.id === data.activePlanId)?.code}</span></div>
              <div className="workload-bars">{data.engineers.map((engineer) => { const percent = Math.round(engineer.load_minutes / 480 * 100); return <div key={engineer.id}><span>{engineer.name}</span><div><i style={{ width: `${Math.min(100, percent)}%`, background: engineer.color }} /></div><b>{percent}%</b></div>; })}</div>
              <div className="chart-axis"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
            </section>

            <section className="chart-card request-types">
              <div className="card-head"><div><h2>Типы работ</h2><p>{data.requests.length} заявок за день</p></div><button className="icon-button"><ChevronDown size={16} /></button></div>
              <div className="type-bars">{typeCounts.map((item) => <div key={item.label}><span>{item.label}</span><div><i style={{ width: `${item.count / maxType * 100}%`, background: item.color }} /></div><b>{item.count}</b></div>)}</div>
              <div className="priority-note"><span className="priority-medal">1</span><p><strong>Аварии обработаны первыми</strong><small>Среднее ожидание — 18 минут</small></p></div>
            </section>

            <section className="chart-card coverage-card">
              <div className="card-head"><div><h2>Результат планирования</h2><p>Распределение всех заявок</p></div></div>
              <div className="donut-wrap"><div className="donut" style={{ "--value": `${Math.round(data.metrics.assigned / data.requests.length * 100)}%` } as React.CSSProperties}><span><b>{data.metrics.assigned}</b><small>назначено</small></span></div><div className="donut-legend"><span><i className="assigned" />Назначено <b>{data.metrics.assigned}</b></span><span><i className="unassigned" />Без назначения <b>{data.metrics.unassigned}</b></span><span><i className="cancelled" />Отменено <b>{data.requests.filter((item) => item.status === "CANCELLED").length}</b></span></div></div>
            </section>

            <section className="chart-card compare-card">
              <div className="card-head"><div><h2>Сравнить планы</h2><p>Изменения маршрутов и назначений</p></div><GitCompareArrows size={18} /></div>
              <div className="compare-selects"><label><span>Базовый</span><select value={oldPlanId} onChange={(event) => setOldPlanId(event.target.value)}>{data.plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.code}</option>)}</select></label><span className="compare-arrow">→</span><label><span>Новый</span><select value={newPlanId} onChange={(event) => setNewPlanId(event.target.value)}>{data.plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.code}</option>)}</select></label></div>
              <div className="compare-stats"><div><b>3</b><span>назначения</span></div><div><b>−8%</b><span>пробег</span></div><div><b>+6%</b><span>охват</span></div></div>
              <button className="button secondary wide" onClick={() => void onOpenComparison(oldPlanId, newPlanId)}><GitCompareArrows size={16} /> Открыть сравнение</button>
            </section>
          </div>

          <section className="plans-table-card">
            <div className="card-head"><div><h2>Версии плана</h2><p>Каждый расчёт сохранён и доступен для проверки</p></div><button className="button ghost"><ArrowDownToLine size={16} /> Экспорт списка</button></div>
            <div className="plans-table"><div className="table-head"><span>Версия</span><span>Создан</span><span>Статус</span><span>Заявки</span><span>Пробег</span><span>Автор</span></div>{data.plans.map((plan, index) => <div className="table-row" key={plan.id}><span><CircleDot size={14} className={`plan-dot ${plan.status}`} /><strong>{plan.code}</strong></span><span>{formatDateTime(plan.created_at)}</span><span><PlanStatusPill status={plan.status} /></span><span>{plan.assigned_count}/{plan.requests_count}</span><span>{formatDistance(data.metrics.distance_meters + index * 7400)}</span><span>{index === 0 ? "planner" : "dispatcher"}</span></div>)}</div>
          </section>
        </>
      ) : (
        <section className="audit-card">
          <div className="audit-tools"><label className="search-field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Действие, объект или автор" /></label><button className="filter-button"><CalendarDays size={15} /> 17 августа</button><button className="filter-button"><Filter size={15} /> Все действия</button></div>
          <div className="audit-list">{filteredAudit.map((item, index) => <article key={item.id}><span className={`audit-node audit-${index % 4}`}><History size={15} /></span><div className="audit-main"><div><strong>{item.action}</strong><span>{item.entity} · {item.entity_id}</span></div><p>{item.details}</p></div><div className="audit-meta"><strong>{item.actor}</strong><span>{formatDateTime(item.timestamp)}</span></div></article>)}</div>
        </section>
      )}
    </div>
  );
}
