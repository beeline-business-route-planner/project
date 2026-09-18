.PHONY: help \
        up down build logs ps \
        upgrade downgrade migrate \
        format lint lint-fix typecheck check \
        run

SRC := src

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
	uv run ruff format $(SRC)

lint:
	uv run ruff check $(SRC)

lint-fix:
	uv run ruff format $(SRC)
	uv run ruff check --fix $(SRC)

typecheck:
	uv run mypy $(SRC)

check:
	uv run ruff format --check $(SRC)
	uv run ruff check $(SRC)
	uv run mypy $(SRC)
