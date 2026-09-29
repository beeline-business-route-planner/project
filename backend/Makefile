.PHONY: help \
        up down build logs ps \
        upgrade downgrade migrate \
        format lint lint-fix typecheck check \
        run test test-integration test-e2e test-full test-matrix test-matrix-update

SRC := src
PY_PATHS := src tests

help:
	@echo ""
	@echo "  Docker"
	@echo "    up                        собрать и поднять весь стек"
	@echo "    down                      остановить и убрать стек"
	@echo "    build                     пересобрать образ backend"
	@echo "    logs                      логи всех контейнеров"
	@echo "    ps                        статус контейнеров"
	@echo ""
	@echo "  Миграции"
	@echo "    upgrade                   применить все миграции"
	@echo "    downgrade REV=<rev>       откатить до ревизии"
	@echo "    migrate MSG=<msg>         создать автомиграцию"
	@echo ""
	@echo "  Качество кода"
	@echo "    check                     формат + линт + типы"
	@echo "    format                    форматирование ruff"
	@echo "    lint                      проверка линтером"
	@echo "    lint-fix                  форматирование + автоисправление линтера"
	@echo "    typecheck                 проверка типов mypy"
	@echo ""
	@echo "  Разработка"
	@echo "    run                       запустить приложение локально (без docker)"
	@echo "    test                      быстрые unit-тесты, без Docker и сети"
	@echo "    test-integration          миграции и PostgreSQL в Docker"
	@echo "    test-e2e                  E2E с одноразовым PostgreSQL в Docker"
	@echo "    test-full                 unit + integration + E2E"
	@echo "    test-matrix               проверить каталог сценариев"
	@echo ""

# === Docker ===

up:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build backend

logs:
	docker compose logs -f

ps:
	docker compose ps

# === Migrations ===

upgrade:
	uv run alembic upgrade head

downgrade:
	uv run alembic downgrade $(REV)

migrate:
	uv run alembic revision --autogenerate -m "$(MSG)"

# === Dev ===

run:
	uv run python -m src

# === Quality ===

format:
	uv run ruff format $(PY_PATHS)

lint:
	uv run ruff check $(PY_PATHS)

lint-fix:
	uv run ruff format $(PY_PATHS)
	uv run ruff check --fix $(PY_PATHS)

typecheck:
	uv run mypy $(SRC)

check:
	uv run ruff format --check $(PY_PATHS)
	uv run ruff check $(PY_PATHS)
	uv run mypy $(SRC)

test:
	uv run pytest tests --suite=unit --cov=src --cov-branch \
		--cov-report=term:skip-covered --cov-fail-under=65

test-integration:
	uv run pytest tests --suite=integration

test-e2e:
	uv run pytest tests --suite=e2e

test-full:
	uv run pytest tests --suite=full --cov=src --cov-branch --cov-report=term:skip-covered

test-matrix:
	uv run python -m tests.support.matrix --check

test-matrix-update:
	uv run python -m tests.support.matrix
