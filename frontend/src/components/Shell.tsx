import type { ReactNode } from "react";
import {
  Bell,
  BookOpenText,
  CalendarDays,
  ChevronDown,
  CircleHelp,
  History,
  LayoutDashboard,
  Menu,
  RefreshCw,
  Route,
  Settings,
  X,
} from "lucide-react";
import type { DataSource, PlannerController } from "../hooks/usePlanner";
import { API_BASE_URL } from "../api/client";
import { BeelineLogo } from "./BeelineLogo";

export type Page = "dashboard" | "planning" | "journal";

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
  const scenario = data.scenarios.find((item) => item.id === data.scenarioId) ?? data.scenarios[0];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <BeelineLogo />
        </div>

        <nav className="main-nav" aria-label="Основная навигация">
          <span className="nav-caption">Рабочее место</span>
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={page === item.id ? "active" : ""} onClick={() => onPageChange(item.id)}>
                <Icon size={18} />
                {item.label}
                {item.id === "planning" && data.plans.some((plan) => plan.status === "draft") ? <em>1</em> : null}
              </button>
            );
          })}
        </nav>

        <div className="sidebar-bottom">
          <button><BookOpenText size={17} /> Инструкция</button>
          <button><Settings size={17} /> Настройки</button>
          <div className="user-card">
            <span className="user-avatar">ДП</span>
            <div><strong>Диспетчер</strong><small>Юго-восток</small></div>
            <ChevronDown size={15} />
          </div>
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="Открыть меню"><Menu size={20} /></button>
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
            <button className="icon-button" aria-label="Помощь"><CircleHelp size={18} /></button>
            <button className="icon-button notification" aria-label="Уведомления"><Bell size={18} /><i /></button>
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
    </div>
  );
}
