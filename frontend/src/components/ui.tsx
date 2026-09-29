import type { ReactNode } from "react";
import {
  Bike,
  BusFront,
  CarFront,
  CircleUserRound,
  Footprints,
  Siren,
  Wrench,
  Zap,
} from "lucide-react";
import type { PlanStatus, RequestStatus, Skill, Transport } from "../api/types";

export const statusLabels: Record<RequestStatus, string> = {
  NOT_SENT: "Не назначена",
  SENT: "Отправлена",
  EN_ROUTE: "В пути",
  IN_PROGRESS: "В работе",
  COMPLETED: "Выполнена",
  OVERDUE: "Просрочена",
  CANCELLED: "Отменена",
};

export const planStatusLabels: Record<PlanStatus, string> = {
  // Wording of the user case: pending / approved / rejected; "Текущий" is a separate badge.
  draft: "Ожидает решения",
  approved: "Утверждён",
  superseded: "Утверждён ранее",
  rejected: "Отклонён",
};

export const skillLabels: Record<Skill, string> = {
  connection: "Подключение",
  emergency: "Авария",
  local: "Локальные работы",
};

export const transportLabels: Record<Transport, string> = {
  car: "Автомобиль",
  walking: "Пешком",
  bicycle: "Велосипед",
  transit: "Общественный транспорт",
};

export function StatusPill({ status }: { status: RequestStatus }) {
  return <span className={`status-pill status-${status.toLowerCase()}`}>{statusLabels[status]}</span>;
}

export function PlanStatusPill({ status }: { status: PlanStatus }) {
  return <span className={`plan-pill plan-${status}`}>{planStatusLabels[status]}</span>;
}

export function TransportIcon({ transport, size = 15 }: { transport: Transport; size?: number }) {
  if (transport === "car") return <CarFront size={size} />;
  if (transport === "walking") return <Footprints size={size} />;
  if (transport === "bicycle") return <Bike size={size} />;
  return <BusFront size={size} />;
}

export function SkillIcon({ skill, size = 15 }: { skill: Skill; size?: number }) {
  if (skill === "emergency") return <Siren size={size} />;
  if (skill === "connection") return <Zap size={size} />;
  return <Wrench size={size} />;
}

export function Avatar({ name, color = "#ffd400", small = false }: { name: string; color?: string; small?: boolean }) {
  const initials = name
    .split(" ")
    .slice(0, 2)
    .map((part) => part[0])
    .join("");
  return (
    <span className={`avatar ${small ? "avatar-small" : ""}`} style={{ backgroundColor: color }}>
      {initials || <CircleUserRound size={16} />}
    </span>
  );
}

export function EmptyState({ icon, title, text, action }: { icon: ReactNode; title: string; text: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <span className="empty-icon">{icon}</span>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}

export function formatTime(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function formatShift(engineer: { shift_start: string | null; shift_end: string | null }) {
  return engineer.shift_start && engineer.shift_end
    ? `${formatTime(engineer.shift_start)}–${formatTime(engineer.shift_end)}`
    : "Смена не указана";
}

export function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function formatDistance(meters: number) {
  return `${(meters / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} км`;
}

export function formatDuration(seconds: number) {
  const minutes = Math.round(seconds / 60);
  return `${Math.floor(minutes / 60)} ч ${minutes % 60} мин`;
}
