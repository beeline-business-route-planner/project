# Frontend диспетчера

React + TypeScript + Vite: контроль дня, карта заявок и инженеров, создание и
утверждение планов, история версий и отчёты. Реальные сценарии, API-вызовы,
режимы данных и ограничения описаны в [`../docs/FRONTEND.md`](../docs/FRONTEND.md).
Backend-контракт — в [`../docs/BACKEND.md`](../docs/BACKEND.md).

## Запуск

```bash
cd frontend
npm ci
cp .env.example .env
npm run dev
```

Открыть <http://localhost:5173>. Vite проксирует `/api` на backend
`127.0.0.1:8000`; он запускается отдельно по [`backend/README.md`](../backend/README.md).
В локальном `.env` укажите браузерный `VITE_2GIS_KEY` для MapGL и при необходимости
`VITE_2GIS_DIRECTIONS_KEY` для дорожной линии. Эти ключи доступны в браузере:
ограничьте их по домену в кабинете 2ГИС. `.env` не коммитьте.

Для проверки **реального** API установите `VITE_DEMO_MODE=false`: режим `auto`
может показать демоданные при недоступности backend. `true` — принудительное
демо. Без backend или актуальных XLSX сегодняшнего дня сквозное планирование
проверить нельзя.

Контроль дня умеет менять статус заявки через `PATCH /api/requests/{id}/status`;
отмена выполняется через событие планирования. Ручное назначение в backend пока
не реализовано. На карте план даёт точки; дорогу между ними для выбранного
инженера запрашивает браузер у 2ГИС Directions, поэтому при недоступности сервиса
точки видны без линии.

## Проверка и навигация

```bash
npm run typecheck
npm run build
```

`src/api/` — HTTP и типы, `src/hooks/usePlanner.ts` — загрузка и адаптация данных,
`src/pages/` — экраны, `src/components/MapPanel.tsx` — карта. Матрица требований и
исторических решений — [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md), но для
фактического поведения ориентируйтесь на код и backend OpenAPI.
