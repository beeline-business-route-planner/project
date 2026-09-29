# Планирование выездов инженеров «Билайн Бизнес»

Рабочее место диспетчера: загрузка заявок и инженеров, построение маршрутов на день,
утверждение плана, перепланирование при изменениях, просмотр карты и выгрузка отчётов.
Система планирует каждый из трёх округов независимо: Восток, Юго-восток и Югоцентр.

В репозитории один backend на FastAPI и frontend на React/Vite. Алгоритм работает
внутри backend; DaData геокодирует адреса, OSRM или 2ГИС поставляет матрицы времени
пути, PostgreSQL хранит версии планов, S3/MinIO — исходные файлы и временные экспорты.
Это не набор развёртываемых микросервисов.

## Быстрый запуск (всё в Docker)

Нужен только Docker с Compose v2.24+, а также ключи DaData и 2ГИС.

```bash
cp -n backend/.env.example backend/.env   # если нет .env; впишите DADATA_API_KEY
cp -n frontend/.env.example frontend/.env # если нет .env; впишите VITE_2GIS_KEY
docker compose up -d --build
```

Это те же два файла, что и для разработки: отдельного корневого `.env` нет.

Откройте <http://localhost:8088>. Это единственный адрес, нужный пользователю:
nginx отдаёт приложение и сам проксирует `/api` на backend и `/dgis-routing` на 2ГИС,
добавляя ключ маршрутов на сервере. Поэтому в браузере не видно ни адреса backend,
ни ключа маршрутизации; виден только ключ карты MapGL — он публичный по своей
природе, ограничьте его по домену в кабинете 2ГИС. Postgres, MinIO, backend и
мониторинг слушают только `127.0.0.1`. Чтобы открыть приложение в локальной сети,
запустите `FRONTEND_HOST=0.0.0.0 docker compose up -d` (порт — `FRONTEND_PORT`).
Остановить: `docker compose down`.
После правок во фронте достаточно `docker compose up -d --build --no-deps frontend` —
без `--no-deps` Compose пересоздаст и backend.

Сервисы бэкенда описаны в `backend/docker-compose.yml` и подключаются корневым
`docker-compose.yml` со своим `backend/.env`; `backend/config.toml` необязателен — ключи
можно задать в `backend/.env`. Фронтенд в Docker берёт ключи 2ГИС из `frontend/.env`:
ключ карты попадает в сборку, ключ маршрутов (`DGIS_ROUTING_KEY`) — только в nginx.

## Разработка

```bash
cd backend && cp -n .env.example .env && cp -n config.toml.example config.toml && make up
cd ../frontend && npm ci && cp -n .env.example .env && npm run dev
```

Frontend: <http://localhost:5173>, backend: <http://localhost:8000>, интерактивная
схема API: <http://localhost:8000/docs>. Vite перенаправляет `/api` на backend и
`/dgis-routing` на 2ГИС с ключом из `frontend/.env` (`DGIS_ROUTING_KEY`).
Для проверки именно реальной интеграции установите `VITE_DEMO_MODE=false` в локальном
`frontend/.env`: режим `auto` может показать демоданные, если `/api/ping` недоступен.
Если backend отвечает, но планов нет, интерфейс остаётся в API-режиме и показывает
пустой округ. По умолчанию Compose занимает порт PostgreSQL `127.0.0.1:5432`;
если он занят, настройте локальный override, не меняя общие файлы проекта.
Остановить стек: `cd backend && make down`.

Первичный импорт принимает **две XLSX-книги на округ** — заявки и инженеры — с датой
текущего рабочего дня по Москве; по умолчанию считает `balanced` + `lns`. CSV не
поддерживается. Исторические книги без режима симуляции не подходят.
Контрольное распределение из исходных материалов не заменяет книгу инженеров.

## Ориентиры для разработчика

<<<<<<< HEAD
Для технической комиссии подготовлен отдельный подробный комплект: [технический путеводитель](tech-commission/README.md). В нём есть запуск, сквозное демо, API, алгоритм и архитектура обеих частей.

- [Архитектура и карта репозитория](docs/ARCHITECTURE.md) — компоненты и путь запроса.
- [Backend: реальные сценарии и HTTP-контракт](docs/BACKEND.md) — Excel, планы,
  события, ответы и ошибки.
- [Frontend: экраны и интеграция](docs/FRONTEND.md) — карта, режимы данных,
  пользовательские действия и ограничения.
- [Материалы заказчика и приоритет источников](docs/README.md) — ТЗ и уточнения.
- [Backend README](backend/README.md) и [frontend README](frontend/README.md) — команды
  для разработки каждого приложения.
=======
`backend/src/api/` содержит маршруты и сценарии, `backend/src/core/` — БД,
алгоритм и внешние интеграции; `frontend/src/pages/` — три экрана,
`frontend/src/hooks/usePlanner.ts` — загрузку и адаптацию планов,
`frontend/src/api/` — HTTP и типы. Действующий контракт — в `/docs` backend;
[backend README](backend/README.md) и [frontend README](frontend/README.md)
дают команды каждого приложения. Исходное ТЗ и решения — в
[проектных материалах](docs/README.md), целевые user cases — в
[`backend/docs/user-case/`](backend/docs/user-case/README.md). При расхождении
старой спецификации с поведением проверяйте код и OpenAPI.
>>>>>>> origin/dev

Проверки: `cd backend && make check && make test`;
`cd frontend && npm run typecheck && npm run build`. DB/E2E-наборы требуют Docker;
запуск описан в [backend/tests/README.md](backend/tests/README.md).
