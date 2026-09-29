import { useEffect, useState, type ReactNode } from "react";
import { CalendarDays, ChevronDown, Menu, X } from "lucide-react";
import { BellSimpleIcon } from "@phosphor-icons/react/dist/csr/BellSimple";
import { BookOpenTextIcon } from "@phosphor-icons/react/dist/csr/BookOpenText";
import { PathIcon } from "@phosphor-icons/react/dist/csr/Path";
import { QuestionIcon } from "@phosphor-icons/react/dist/csr/Question";
import { ChartBarIcon } from "@phosphor-icons/react/dist/csr/ChartBar";
import { SquaresFourIcon } from "@phosphor-icons/react/dist/csr/SquaresFour";
import type { DataSource, PlannerController } from "../hooks/usePlanner";
import { API_BASE_URL } from "../api/client";
import { BeelineLogo } from "./BeelineLogo";

export type Page = "dashboard" | "planning" | "analytics";
type UtilityPanel = "help" | "notifications" | "instructions";

interface ShellProps {
  page: Page;
  onPageChange: (page: Page) => void;
  planner: PlannerController;
  children: ReactNode;
}

const nav = [
  { id: "dashboard" as const, label: "Контроль дня", icon: SquaresFourIcon },
  { id: "planning" as const, label: "Планирование", icon: PathIcon },
  { id: "analytics" as const, label: "Аналитика", icon: ChartBarIcon },
];

function moscowToday() {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

function russianDate(date: string) {
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" }).format(new Date(`${date}T12:00:00`));
}

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
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarDismissed, setSidebarDismissed] = useState(false);
  const [utilityPanel, setUtilityPanel] = useState<UtilityPanel | null>(null);
  const [notificationsRead, setNotificationsRead] = useState(false);
  const [pushVisible, setPushVisible] = useState(false);
  const [today, setToday] = useState(moscowToday);
  const scenario = data.scenarios.find((item) => item.id === data.scenarioId) ?? data.scenarios[0];
  const overdueCount = data.requests.filter((item) => item.status === "OVERDUE").length;
  const unassignedCount = data.requests.filter((item) => !item.engineer_id && item.status !== "CANCELLED").length;
  const draftCount = data.plans.filter((item) => item.status === "draft").length;
  const notificationCount = overdueCount + unassignedCount + draftCount;
  const viewingAnotherDay = data.planningDate !== today;

  useEffect(() => {
    const timer = window.setInterval(() => setToday(moscowToday()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!utilityPanel) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setUtilityPanel(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [utilityPanel]);

  useEffect(() => {
    if (!notificationCount) return;
    const showTimer = window.setTimeout(() => setPushVisible(true), 650);
    const hideTimer = window.setTimeout(() => setPushVisible(false), 4650);
    return () => {
      window.clearTimeout(showTimer);
      window.clearTimeout(hideTimer);
    };
  }, [notificationCount]);

  const openUtility = (panel: UtilityPanel) => {
    setPushVisible(false);
    setSidebarDismissed(true);
    setUtilityPanel(panel);
    if (panel === "notifications") setNotificationsRead(true);
  };

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileSidebarOpen ? "mobile-open" : ""} ${sidebarDismissed ? "dismissed" : ""}`} onMouseLeave={() => { setMobileSidebarOpen(false); setSidebarDismissed(false); }}>
        <button className="brand brand-home" onClick={() => { onPageChange("dashboard"); setMobileSidebarOpen(false); setSidebarDismissed(true); }} aria-label="На главную — Контроль дня"><BeelineLogo /></button>

        <nav className="main-nav" aria-label="Основная навигация">
          <span className="nav-caption">Рабочее место</span>
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={page === item.id ? "active" : ""} onClick={() => { onPageChange(item.id); setMobileSidebarOpen(false); setSidebarDismissed(true); }}>
                <Icon size={18} />
                <span className="nav-label">{item.label}</span>
                {item.id === "planning" && data.plans.some((plan) => plan.status === "draft") ? <em>1</em> : null}
              </button>
            );
          })}
        </nav>

        <div className="sidebar-bottom">
          <button onClick={() => openUtility("instructions")}><BookOpenTextIcon size={18} /><span className="nav-label">Инструкция</span></button>
          <div className="user-card">
            <span className="user-avatar">ДП</span>
            <div><strong>Диспетчер</strong><small>{scenario?.name ?? "Участок"}</small></div>
            <ChevronDown size={15} />
          </div>
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="Открыть меню" onClick={() => setMobileSidebarOpen((current) => !current)}><Menu size={20} /></button>
          <div className="context-selects">
            <div className="today-context"><span>Сегодня</span><strong>{russianDate(today)}</strong></div>
            <label>
              <span>Участок</span>
              <select
                value={data.scenarioId}
                onChange={(event) => void planner.changeContext(event.target.value, "")}
              >
                {data.scenarios.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
            <label>
              <span>{viewingAnotherDay ? "Просмотр плана за" : "Рабочий день"}</span>
              <div className="input-with-icon">
                <CalendarDays size={15} />
                <select
                  value={data.planningDate}
                  onChange={(event) => void planner.changeContext(data.scenarioId, event.target.value)}
                >
                  {(scenario?.planning_dates ?? [data.planningDate]).map((date) => (
                    <option key={date} value={date}>{russianDate(date)}</option>
                  ))}
                </select>
              </div>
            </label>
            {viewingAnotherDay ? <span className="historical-date-note" title="Плана на сегодня нет среди полученных от backend дат">Архивный день</span> : null}
          </div>
          <div className="topbar-actions">
            <ConnectionBadge source={planner.source} />
            <button className="icon-button" onClick={() => openUtility("help")} aria-label="Помощь" title="Помощь"><QuestionIcon size={19} /></button>
            <button className="icon-button notification" onClick={() => openUtility("notifications")} aria-label={`Уведомления: ${notificationCount}`} title="Уведомления"><BellSimpleIcon size={19} />{notificationCount > 0 && !notificationsRead ? <i /> : null}</button>
          </div>
        </header>

        <main className="content">{children}</main>
      </div>

      {planner.loading ? (
        <div className="loading-screen"><span className="spinner" /><strong>Загружаем рабочий день</strong></div>
      ) : null}
      {planner.error ? (
        <div className="system-banner">
          <div><strong>{planner.source === "demo" ? "Показан демонстрационный сценарий" : "Ошибка загрузки данных"}</strong><span>{planner.error}</span></div>
          <button onClick={planner.dismissError}><X size={16} /></button>
        </div>
      ) : null}
      {planner.notice ? <div className="toast"><span className="toast-check">✓</span>{planner.notice}</div> : null}

      {pushVisible && !utilityPanel ? (
        <div className="push-notification" role="status" aria-live="polite">
          <span className="push-icon"><BellSimpleIcon size={18} weight="fill" /></span>
          <button className="push-main" onClick={() => openUtility("notifications")}>
            <strong>Есть события рабочего дня</strong>
            <span>{overdueCount ? `${overdueCount} просрочена · ` : ""}{unassignedCount ? `${unassignedCount} без назначения` : `${draftCount} черновик плана`}</span>
          </button>
          <button className="push-close" onClick={() => setPushVisible(false)} aria-label="Закрыть уведомление"><X size={16} /></button>
          <i className="push-progress" />
        </div>
      ) : null}

      {utilityPanel ? (
        <div className="utility-layer" onMouseDown={() => setUtilityPanel(null)}>
          <aside className="utility-drawer" role="dialog" aria-modal="true" aria-labelledby="utility-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="utility-head">
              <div>
                <span>{utilityPanel === "notifications" ? `${notificationCount} событий` : "Рабочее место диспетчера"}</span>
                <h2 id="utility-title">{{ help: "Помощь", notifications: "Уведомления", instructions: "Инструкция" }[utilityPanel]}</h2>
              </div>
              <button className="icon-button" onClick={() => setUtilityPanel(null)} aria-label="Закрыть"><X size={18} /></button>
            </div>

            {utilityPanel === "help" ? (
              <div className="utility-content">
                <section><strong>Контроль дня</strong><p>Выберите заявку или инженера — справа откроются детали, а карта подсветит связанный маршрут.</p></section>
                <section><strong>Планирование</strong><p>Импортируйте XLSX, рассчитайте вариант и проверьте причины заявок без назначения до утверждения.</p></section>
                <section><strong>Аналитика и история</strong><p>В аналитике — показатели дня и PDF-отчёт. В истории версий — сохранённые расчёты, сравнение и журнал действий.</p></section>
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
                <section><span>01</span><div><strong>Выберите день</strong><p>Сверху выберите участок и дату. В списке только дни, для которых уже есть план. Для нового дня откройте «Планирование» и загрузите два XLSX: заявки и инженеры одного округа.</p></div></section>
                <section><span>02</span><div><strong>Посмотрите заявки и карту</strong><p>На главной видны точки заявок. Нажмите заявку, чтобы прочесть адрес и ограничения. Переключитесь на «Инженеры» и нажмите человека, чтобы увидеть только его маршрут.</p></div></section>
                <section><span>03</span><div><strong>Отметьте фактический статус</strong><p>Откройте заявку на главной и выберите её новый статус справа: «В пути», «В работе», «Выполнена» и другие. Изменение сохранится через API. Для отмены не используйте список статусов — создайте событие в планировании.</p></div></section>
                <section><span>04</span><div><strong>Сообщите об изменении</strong><p>В «Планировании» нажмите «Новое событие»: инженер выбыл или вернулся, заявка отменена или добавилась. Для новой заявки укажите тип, адрес и окно. Окно должно относиться к выбранному дню и ещё не закончиться.</p></div></section>
                <section><span>05</span><div><strong>Проверьте и решите</strong><p>После расчёта откройте новый черновик: посмотрите назначения, причины неназначенных и изменения. Нажмите «Утвердить» или «Отклонить». Пока событие ждёт решения, следующее событие бэкенд не принимает.</p></div></section>
                <section><span>06</span><div><strong>Скачайте результат</strong><p>XLSX выбранного плана скачивается в «Планировании». Показатели и ZIP с PDF-отчётами — в «Аналитике». Предыдущие расчёты — в «Истории версий».</p></div></section>
              </div>
            ) : null}
          </aside>
        </div>
      ) : null}
    </div>
  );
}
