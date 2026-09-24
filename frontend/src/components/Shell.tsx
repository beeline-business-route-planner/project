import { useEffect, useState, type ReactNode } from "react";
import {
  Bell,
  BookOpenText,
  CalendarDays,
  ChevronDown,
  CircleHelp,
  History,
  LayoutDashboard,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  Route,
  Settings,
  X,
} from "lucide-react";
import type { DataSource, PlannerController } from "../hooks/usePlanner";
import { API_BASE_URL } from "../api/client";
import { BeelineLogo } from "./BeelineLogo";

export type Page = "dashboard" | "planning" | "journal";
type UtilityPanel = "help" | "notifications" | "instructions" | "settings";

interface ShellProps {
  page: Page;
  onPageChange: (page: Page) => void;
  planner: PlannerController;
  children: ReactNode;
}

const nav = [
  { id: "dashboard" as const, label: "Контроль дня", icon: LayoutDashboard },
  { id: "planning" as const, label: "Планирование", icon: Route },
  { id: "journal" as const, label: "Журнал и отчёты", icon: History },
];

function ConnectionBadge({ source }: { source: DataSource }) {
  return (
    <div className={`connection-badge ${source}`} title={source === "api" ? API_BASE_URL : "Локальные демонстрационные данные"}>
      <span />
      {source === "api" ? "API подключён" : "Демо-режим"}
    </div>
  );
}

export function Shell({ page, onPageChange, planner, children }: ShellProps) {
  const { data } = planner;
  const [sidebarPinned, setSidebarPinned] = useState(false);
  const [utilityPanel, setUtilityPanel] = useState<UtilityPanel | null>(null);
  const [notificationsRead, setNotificationsRead] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(() => localStorage.getItem("planner-reduced-motion") === "true");
  const [largeUi, setLargeUi] = useState(() => localStorage.getItem("planner-large-ui") !== "false");
  const scenario = data.scenarios.find((item) => item.id === data.scenarioId) ?? data.scenarios[0];
  const overdueCount = data.requests.filter((item) => item.status === "OVERDUE").length;
  const unassignedCount = data.requests.filter((item) => !item.engineer_id && item.status !== "CANCELLED").length;
  const draftCount = data.plans.filter((item) => item.status === "draft").length;
  const notificationCount = overdueCount + unassignedCount + draftCount;

  useEffect(() => {
    document.documentElement.classList.toggle("reduce-motion", reducedMotion);
    document.documentElement.classList.toggle("large-ui", largeUi);
    localStorage.setItem("planner-reduced-motion", String(reducedMotion));
    localStorage.setItem("planner-large-ui", String(largeUi));
  }, [largeUi, reducedMotion]);

  useEffect(() => {
    if (!utilityPanel) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setUtilityPanel(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [utilityPanel]);

  const openUtility = (panel: UtilityPanel) => {
    setUtilityPanel(panel);
    if (panel === "notifications") setNotificationsRead(true);
  };

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarPinned ? "expanded pinned" : ""}`}>
        <div className="brand">
          <BeelineLogo />
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarPinned((current) => !current)}
            aria-label={sidebarPinned ? "Свернуть меню" : "Развернуть меню"}
            title={sidebarPinned ? "Свернуть меню" : "Развернуть меню"}
          >
            {sidebarPinned ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />}
          </button>
        </div>

        <nav className="main-nav" aria-label="Основная навигация">
          <span className="nav-caption">Рабочее место</span>
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={page === item.id ? "active" : ""} onClick={() => onPageChange(item.id)}>
                <Icon size={18} />
                <span className="nav-label">{item.label}</span>
                {item.id === "planning" && data.plans.some((plan) => plan.status === "draft") ? <em>1</em> : null}
              </button>
            );
          })}
        </nav>

        <div className="sidebar-bottom">
          <button onClick={() => openUtility("instructions")}><BookOpenText size={17} /><span className="nav-label">Инструкция</span></button>
          <button onClick={() => openUtility("settings")}><Settings size={17} /><span className="nav-label">Настройки</span></button>
          <div className="user-card">
            <span className="user-avatar">ДП</span>
            <div><strong>Диспетчер</strong><small>Юго-восток</small></div>
            <ChevronDown size={15} />
          </div>
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="Открыть меню" onClick={() => setSidebarPinned(true)}><Menu size={20} /></button>
          <div className="context-selects">
            <label>
              <span>Участок</span>
              <select
                value={data.scenarioId}
                onChange={(event) => void planner.changeContext(event.target.value, data.planningDate)}
              >
                {data.scenarios.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
            <label>
              <span>Рабочий день</span>
              <div className="input-with-icon">
                <CalendarDays size={15} />
                <select
                  value={data.planningDate}
                  onChange={(event) => void planner.changeContext(data.scenarioId, event.target.value)}
                >
                  {(scenario?.planning_dates ?? [data.planningDate]).map((date) => (
                    <option key={date} value={date}>{new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" }).format(new Date(`${date}T12:00:00`))}</option>
                  ))}
                </select>
              </div>
            </label>
          </div>
          <div className="topbar-actions">
            <ConnectionBadge source={planner.source} />
            <button className="icon-button" onClick={() => void planner.refresh()} aria-label="Обновить данные" title="Обновить данные"><RefreshCw size={18} /></button>
            <button className="icon-button" onClick={() => openUtility("help")} aria-label="Помощь" title="Помощь"><CircleHelp size={18} /></button>
            <button className="icon-button notification" onClick={() => openUtility("notifications")} aria-label={`Уведомления: ${notificationCount}`} title="Уведомления"><Bell size={18} />{notificationCount > 0 && !notificationsRead ? <i /> : null}</button>
          </div>
        </header>

        <main className="content">{children}</main>
      </div>

      {planner.loading ? (
        <div className="loading-screen"><span className="spinner" /><strong>Загружаем рабочий день</strong></div>
      ) : null}
      {planner.error ? (
        <div className="system-banner">
          <div><strong>Backend сейчас недоступен</strong><span>{planner.error}</span></div>
          <button onClick={planner.dismissError}><X size={16} /></button>
        </div>
      ) : null}
      {planner.notice ? <div className="toast"><span className="toast-check">✓</span>{planner.notice}</div> : null}

      {utilityPanel ? (
        <div className="utility-layer" onMouseDown={() => setUtilityPanel(null)}>
          <aside className="utility-drawer" role="dialog" aria-modal="true" aria-labelledby="utility-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="utility-head">
              <div>
                <span>{utilityPanel === "notifications" ? `${notificationCount} событий` : "Рабочее место диспетчера"}</span>
                <h2 id="utility-title">{{ help: "Помощь", notifications: "Уведомления", instructions: "Инструкция", settings: "Настройки" }[utilityPanel]}</h2>
              </div>
              <button className="icon-button" onClick={() => setUtilityPanel(null)} aria-label="Закрыть"><X size={18} /></button>
            </div>

            {utilityPanel === "help" ? (
              <div className="utility-content">
                <section><strong>Контроль дня</strong><p>Выберите заявку или инженера — справа откроются детали, а карта подсветит связанный маршрут.</p></section>
                <section><strong>Планирование</strong><p>Импортируйте XLSX, рассчитайте вариант и проверьте причины заявок без назначения до утверждения.</p></section>
                <section><strong>Журнал и отчёты</strong><p>Смотрите метрики, версии плана и аудит. Список версий выгружается в CSV, отчёты — в XLSX или PDF при поддержке backend.</p></section>
                <div className="utility-status"><span className={`status-light ${planner.source}`} />Источник данных: <b>{planner.source === "api" ? "backend API" : "демонстрационный набор"}</b></div>
              </div>
            ) : null}

            {utilityPanel === "notifications" ? (
              <div className="utility-content notification-list">
                <section className={overdueCount ? "is-warning" : ""}><strong>Просроченные заявки</strong><b>{overdueCount}</b><p>{overdueCount ? "Требуют внимания диспетчера." : "Просроченных заявок нет."}</p></section>
                <section className={unassignedCount ? "is-warning" : ""}><strong>Без назначения</strong><b>{unassignedCount}</b><p>{unassignedCount ? "Проверьте ограничения в планировании." : "Все активные заявки распределены."}</p></section>
                <section><strong>Черновики плана</strong><b>{draftCount}</b><p>{draftCount ? "Есть вариант, ожидающий проверки." : "Непроверенных черновиков нет."}</p></section>
                <button className="button secondary wide" onClick={() => setNotificationsRead(true)}>Отметить всё прочитанным</button>
              </div>
            ) : null}

            {utilityPanel === "instructions" ? (
              <div className="utility-content instruction-steps">
                <section><span>01</span><div><strong>Проверьте исходные данные</strong><p>Выберите участок и рабочий день в верхней панели.</p></div></section>
                <section><span>02</span><div><strong>Оцените отклонения</strong><p>На экране контроля найдите просрочки, свободных инженеров и незакрытые окна.</p></div></section>
                <section><span>03</span><div><strong>Пересчитайте план</strong><p>Внесите событие или ручную правку, затем сравните новый маршрут с базовым.</p></div></section>
                <section><span>04</span><div><strong>Зафиксируйте результат</strong><p>Утвердите вариант и проверьте запись в журнале действий.</p></div></section>
              </div>
            ) : null}

            {utilityPanel === "settings" ? (
              <div className="utility-content settings-list">
                <label><div><strong>Крупный интерфейс</strong><p>Увеличивает подписи графиков, таблиц и служебный текст.</p></div><input type="checkbox" checked={largeUi} onChange={(event) => setLargeUi(event.target.checked)} /><span /></label>
                <label><div><strong>Минимум анимации</strong><p>Отключает выезды панелей и анимацию диаграмм.</p></div><input type="checkbox" checked={reducedMotion} onChange={(event) => setReducedMotion(event.target.checked)} /><span /></label>
              </div>
            ) : null}
          </aside>
        </div>
      ) : null}
    </div>
  );
}
