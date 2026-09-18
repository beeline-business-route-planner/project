# Кодстайл backend

Описывает, как реально написан код в этом шаблоне (`src/`), чтобы весь новый код выглядел
так, будто его писал один человек. Не выдумано — выведено из существующих файлов
(`src/core/*`, `src/api/*`, `src/config/*`).

## Инструменты — обязательны перед каждым коммитом

```bash
make check   # ruff format --check + ruff check + mypy
# или при необходимости поправить:
make lint-fix
```

- **ruff** — форматирование и линт. Конфиг в `pyproject.toml`:
  - `line-length = 100`
  - `target-version = "py314"`
  - кавычки — **только двойные** (`quote-style = "double"`)
  - активные правила: `E, F, I, W, B, C4, UP, SIM` (pycodestyle, pyflakes, isort, warnings,
    bugbear, comprehensions, pyupgrade, simplify)
- **mypy** — строгая типизация: `check_untyped_defs`, `warn_unused_ignores`,
  `warn_redundant_casts`, `ignore_missing_imports` (для нетипизированных сторонних либ).

Если `ruff` или `mypy` ругаются — правим код, а не подавляем правило точечным `# noqa` /
`# type: ignore` без крайней необходимости. Если подавление всё же нужно — обязательно с
конкретным кодом правила (`# noqa: E501`, `# type: ignore[arg-type]`), не голым.

## Импорты

Импорты сортируются автоматически ruff (`I`, isort-совместимо) на 3 группы, разделённые
пустой строкой: стандартная библиотека → сторонние пакеты → `src.*`. Пример
(`src/main.py`):

```python
import logging
from contextlib import asynccontextmanager

import uvicorn
from dishka import make_async_container
from fastapi import FastAPI, Request

from src.api import router
from src.config import cfg
from src.core.di import DbProvider
```

Внутри пакетов `src` — **только абсолютные импорты** (`from src.core.db.models.base import
Base`), относительные (`from .base import Base`) не используются.

## Типизация

- Типизируем **всё**: сигнатуры функций и методов, возвращаемые значения, атрибуты классов.
  `-> None` пишем явно, даже когда функция ничего не возвращает.
- Generics через новый синтаксис Python 3.12+ (PEP 695), без `TypeVar`:
  ```python
  class BaseRepository[ModelType: Base]:
      model: type[ModelType]
  ```
- Современные типы из `X | Y`, `list[...]`, `dict[...]` — не `Optional[X]`, `List[...]`
  (за это отвечает правило `UP`).
- Для датаклассов с `from_orm` — `typing.Self` как тип возврата classmethod'а.

## Именование

- Файлы и модули — `snake_case`, в единственном числе для одной сущности (`config.py`,
  `middleware.py`), допустимо множественное для пакета с несколькими похожими сущностями
  (`models/`, `repositories/`, `dto/`).
- Классы — `PascalCase` (`UnitOfWork`, `BaseRepository`, `StructuredJsonFormatter`).
- Функции, методы, переменные — `snake_case`.
- Константы модуля — `UPPER_SNAKE_CASE` (`BASE_DIR`, `TOML_SETTINGS_PATH`).
- Приватные атрибуты класса — один подчёркивающий префикс (`self._session`), не двойной.
- Модуль-логгер — всегда называется `log`, объявляется сразу после импортов:
  ```python
  log = logging.getLogger(__name__)
  ```

## Docstring и комментарии

- По умолчанию **без комментариев** — код должен быть понятен через именование.
- Docstring пишем только там, где поведение метода не очевидно из сигнатуры или содержит
  тонкости, которые не следует передавать только именованием параметров.
- Формат — **Google-style**. Заголовки секций (`Args`, `Returns`, `Raises`, `Yields`,
  `Note`, `Example` и т.д.) — **на английском**, ровно как в стандарте, без перевода: это
  фиксированные ключевые слова, которые понимают IDE и генераторы документации. Всё
  остальное — описание метода, описания параметров/возврата/исключений — **на русском**.
  Простой однострочный docstring без секций (как в `src/core/db/models/base.py`) тоже
  целиком на русском, секции ему не нужны:
  ```python
  def to_dict(self) -> dict[str, object]:
      """Преобразует объект модели в словарь по колонкам."""
  ```
- Полный Google-style с секциями — когда у метода есть параметры, есть что сказать про
  возврат, или он бросает исключения, которые вызывающему важно знать:
  ```python
  def build_route(self, engineer: Engineer, requests: list[Request]) -> Route:
      """Строит маршрут инженера с учётом временных окон заявок.

      Args:
          engineer: инженер, для которого строится маршрут.
          requests: заявки, уже отфильтрованные по квалификации и транспорту.

      Returns:
          Маршрут с упорядоченным списком заявок и суммарным пробегом.

      Raises:
          NoFeasibleRouteError: если ни одна заявка не помещается во временные окна
              инженера с учётом его смены.
      """
  ```
- Комментарий внутри кода — только если объясняет неочевидное решение/ограничение
  (пример из `uow.py`):
  ```python
  # Когда появится первая модель и её репозиторий, подключай их сюда явно, например:
  # self.users = UserRepository(self.session)
  ```
  Комментарии, пересказывающие код построчно, не пишем.

## Асинхронность

- Весь I/O (БД, внешние HTTP-вызовы) — только `async`/`await`, синхронных блокирующих
  вызовов в обработчиках запросов быть не должно.
- Асинхронные генераторы для ресурсов с жизненным циклом (сессия БД, UoW) — через
  `AsyncIterator[...]` + `yield`, как в `src/core/di/session.py`.

## Модели, DTO, репозитории

- **SQLAlchemy-модели** наследуются от общего `Base` (`src/core/db/models/base.py`),
  имя таблицы генерируется автоматически как `cls.__name__.lower()` — руками
  `__tablename__` не переопределяем без явной причины.
- **DTO** — обычные `@dataclass`, наследники `BaseDTO`, не содержат ORM-логики, получаются
  из модели через `SomeDTO.from_orm(model_instance)`. DTO никогда не импортируют
  SQLAlchemy.
- **Репозитории** — по одному на модель, наследуют `BaseRepository[ModelType]`, кладём
  только методы доступа к данным (запросы), никакой бизнес-логики.
- Бизнес-правила и оркестрация нескольких репозиториев — в сервисном слое (см.
  `ARCHITECTURE.md`), не в роутере и не в репозитории.

## Конфигурация

- Все настройки — через `pydantic-settings`-модель `Config` (`src/config/config.py`),
  никаких `os.environ[...]` россыпью по коду.
- Секции конфига — вложенные `BaseModel` (`Database`, `Logging`, `CORS`), а не плоский
  список полей.
- Единая точка входа — `from src.config import cfg`, читаем `cfg.database.postgres_host`
  и т.п., глобальный `cfg` создаётся один раз на модуле.

## Логирование

- Только `logging`, без `print()`.
- Формат — структурные JSON-логи (`StructuredJsonFormatter`), дополнительные поля
  передаются через `extra={...}`, не форматированием в строку сообщения:
  ```python
  log.info("HTTP request completed", extra={"http": {"method": ..., "status_code": ...}})
  ```
- `request_id` берётся из контекстной переменной автоматически форматтером — вручную его
  прокидывать в каждый лог не нужно.

## Ошибки и исключения API

- Кастомные HTTP-исключения наследуются от `src.api.exc.base.Base` (сам он —
  `fastapi.HTTPException`) и задают `status_code` и `detail` как **атрибуты класса**, не в
  `__init__`:
  ```python
  class RequestNotFound(Base):
      status_code = 404
      detail = "Заявка не найдена"
  ```
- Непойманные исключения ловятся глобальным `@app.exception_handler(Exception)` в
  `src/main.py` — не оборачиваем каждый роут в `try/except Exception`, только точечные
  бизнес-исключения там, где нужно вернуть осознанный HTTP-статус.

## Pydantic-схемы API (input/output)

- Схемы запросов/ответов роутеров — отдельные `pydantic.BaseModel`, не переиспользуем
  DTO/ORM-модели напрямую как response_model.
- Название: `<Entity><Action>Request` / `<Entity>Response` (например `PlanGenerateRequest`,
  `RequestItemResponse`).

## FastAPI-роутеры

- Роутер собирается декларативно на уровне модуля (`router = APIRouter(prefix="/api")`),
  без функций-фабрик без необходимости.
- Обработчик роута — тонкий: валидация через Pydantic (делает FastAPI сама), вызов
  сервиса/UoW, преобразование результата в response-схему. Никакой прямой работы с
  SQLAlchemy-сессией внутри роутера.

## Общее

- Ничего не оставляем закомментированным "на всякий случай" — либо код нужен, либо
  удаляется.
- Один файл — одна зона ответственности (не смешиваем модели и роутеры в одном модуле).
- Явные, длинные и понятные имена важнее сокращений (`get_sessionmaker`, а не `get_sm`).
