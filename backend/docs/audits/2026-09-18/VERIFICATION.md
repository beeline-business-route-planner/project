# Протокол проверок

Проверки выполнены во время аудита 2026-09-18, до сохранения этой документации. Это сводка результатов, не сырые логи. Временные логи/окружение удалены после завершения. Значения secrets не сохранены.

## Среда и установка

- Backend: `/Users/oleg/Downloads/Хакатон`.
- Исходная .venv: broken link на отсутствующий Python 3.13; не изменялась.
- Использован Python 3.12.14 из bundled runtime и uv.
- Временная среда: `/tmp/beeline-audit-aZBIPO/venv` — уже удалена.
- Frozen dependencies: `UV_PROJECT_ENVIRONMENT=/tmp/beeline-audit-aZBIPO/venv uv sync --frozen --no-install-project --python /Users/oleg/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`.
- Для проверок: PYTHONPATH=src, PYTHONDONTWRITEBYTECODE=1, отдельные temp/cache/database paths. Source/uv.lock не переписывались.

## Команды и результаты

В строках ниже `<python>` означает Python временной audit venv, не существующую сейчас команду для запуска.

| Проверка | Команда / способ | Фактический результат |
|---|---|---|
| Tests | `<python> -m pytest -p no:cacheprovider --basetemp /tmp/beeline-audit-aZBIPO/main-pytest` | 24 passed, 2 warnings, 1.67 s |
| Ruff | `<python> -m ruff check . --no-cache` | All checks passed |
| mypy | `<python> -m mypy src --cache-dir /tmp/beeline-audit-aZBIPO/main-mypy` | Success, no issues in 23 source files |
| SQLite Alembic | heads/history/upgrade head/current/check/downgrade base/upgrade head/check, отдельная temporary DB | Все успешны; head 0001_initial, no new operations |
| PostgreSQL Alembic | Тот же migration cycle на новом PG16 instance | Все успешны |
| Uvicorn | subprocess 127.0.0.1, свободный port, APP_ENV=test, explicit demo providers, temporary DB | health/readiness/docs/openapi 200; процесс остановлен |
| PostgreSQL flow | Existing test_import_plan_approve_replan_diff_and_reports через TestClient, app_env=development, migrated PostgreSQL, demo providers | Import/plan/approve/event/diff/stale approval/reports/dashboard PASS; readiness 200 |
| Live OSRM | Matrix для двух points через текущий adapter | SUCCESS, 2 rows |
| Live Nominatim | Один geocode через adapter | SUCCESS |

Warnings: Starlette TestClient/httpx deprecation и anyio BlockingPortal alias deprecation. Не свидетельствуют о падении suite.

PostgreSQL: после запуска Docker пользователем использован только новый disposable `postgres:16-alpine` container, с опубликованным случайным port на 127.0.0.1. Существующие контейнеры/БД не менялись. Migration downgrade выполнялся исключительно на audit DB. Новый container остановлен и удалён.

## Негативные эксперименты

| Case | Наблюдение | Вид доказательства |
|---|---|---|
| as_of=13:00, engineer office/available 08:00 | Назначение 08:10, validator accepts | In-memory DTO/root |
| Request COMPLETED | Повторно assigned, validator accepts | In-memory DTO/root |
| start раньше arrival | Validator accepts | In-memory DTO/root |
| Same request assigned+unassigned | Validator accepts | In-memory DTO/root |
| Locked times shifted, same engineer | Validator accepts | In-memory DTO/root |
| Unavailable engineer с текущим lock | Planner KeyError; API 500 после commit event | DTO + temporary SQLite/root |
| Retry same failed event | 200 duplicate=True, replanning=None | Temporary SQLite/root |
| Event before UUID flush | Outbox event_id="None", audit object_id="None"; GET audit 500 | Temporary SQLite/root |
| Invalid planning_date | 500 | TestClient/root |
| Reversed request window | 500: validation ctx содержит ValueError | TestClient/root |
| Manual-change initial draft | Новый draft 200; approve child 409 stale_base_plan | TestClient/root |
| IN_PROGRESS(start)→COMPLETED(finish) | Report actual_start=None | TestClient/root |
| Combined work subtype | equipment_order, service20/full40 | Importer call/root; correctness unresolved |
| Synthetic DGIS key в HTTPX log | Найден в INFO log | Mock/no real key/root |
| Negative DGIS source_id | Записан последний source row | Mock/root |
| DGIS JSON array | Uncaught AttributeError | Mock/root |
| XLSX external_id `=1+1` | Cell data_type=f | Renderer in-memory/root; no formula execution |

Дополнительные independent planner review observations: wrong assignment destination accepted; missing matrix validation skipped; model_copy bypasses matrix shape validation; shallow input mutability; stale lock может отодвинуть ready time назад; feasible one-engineer solution не выбирается demo; reason aggregation может неверно объяснить drop; CancelledError оставляет run незавершённым. Это не оценка неизвестного алгоритма Юрия.

## Ограничения

- Полный pytest использует SQLite fixtures; PostgreSQL проверен основным flow, не всей suite.
- 2GIS live не запускался: configured key отсутствует. Scopes/licensed traffic не подтверждены.
- Успех OSRM/Nominatim не доказывает readiness default 2GIS.
- Алгоритм Юрия отсутствует в дереве, mathematical quality/timeout не проверены.
- API Docker image/full compose stack не собирались.
- Concurrency race tests, CVE scan, ZIP-bomb/DoS и исполнение опасных Excel formulas не выполнялись.
- Coverage percentage не измерялся; 24 passing tests не доказывают completeness.
- В двух read-only CLI-ролях temporary-file permissions мешали pytest/mypy/startup/migration checks. Основные команды повторены root в доступной среде и прошли.
- Две CLI-роли остановились usage limit до final report. Четыре роли завершили final conclusions, шесть запущены.
- Возможность восстановить точный stdout после cleanup отсутствует; данный протокол сохраняет результаты и границы, не обещает raw evidence files.

## Проверка после начала исправлений

2026-09-19, P0-04 (частично):

- `.venv/bin/python -m pytest -p no:cacheprovider` — 27 passed, 2 прежних deprecation warnings;
- `.venv/bin/python -m ruff check . --no-cache` — All checks passed;
- `.venv/bin/python -m mypy src` — Success, 23 source files;
- `MYPYPATH=src .venv/bin/python -m mypy tests/test_planner_contract.py` — Success.

Первая попытка pytest после `uv sync --no-install-project` не собрала tests: пакет не был установлен и PYTHONPATH не был задан. После обычного `uv sync --frozen`, соответствующего README, suite прошёл. Отдельный запуск mypy для test-файла без `MYPYPATH=src` видел установленный editable package как untyped; повтор с исходным деревом прошёл. Эти две ошибки относятся к командам проверки, не к runtime-поведению приложения. После реорганизации test-файла editable marker среды перестал добавлять пакет в import path; `uv pip install -e .` восстановил локальную установку, после чего полный suite из 27 tests прошёл.

## Контрольные суммы

Контрольные суммы обновлены при переносе проверенного backend в командный monorepo. Они фиксируют содержимое первого импортирующего коммита; локальные environment/cache/data файлы не входят.

| Файл относительно backend | SHA-256 |
|---|---|
| `Dockerfile` | `c63c8019c483b59993e61769d3e88aba41783096a6ea18b059d67cb40b682884` |
| `alembic/env.py` | `47b5bb060e3d132199579b6e5ba02b908842d404f706c89a6054a436a0807f71` |
| `alembic/script.py.mako` | `c20f6ab92d4ed36d77fbccb82bc410cd2ced42f2c162eebb43ddd45ae93dd90e` |
| `alembic/versions/0001_initial.py` | `382a9030358d01b93509733b7c8e734a91cace273ae62a541d2297f59d37fda7` |
| `alembic.ini` | `48064894075f6971067e1852e318e46f0df1da22465acbbbe356404f3c7b089f` |
| `docker-compose.yml` | `6ce73f84cf7466cc172a377bb4a98c21a326c24eee263d12519e7624cda81bb8` |
| `pyproject.toml` | `b9a94d4c31e1049c0bba1dfae2748e967a06faf7a3b7fa554cc305b80afcede1` |
| `src/beeline_backend/__init__.py` | `abf1ee67e01ced355a1c4c750fdaedb232f4239c1c28c5880514df1ba7d4cf99` |
| `src/beeline_backend/application/__init__.py` | `2b57cbb7e3d87c930dca3a0bc1636897931a4f641f2d3919e4083e379e020f20` |
| `src/beeline_backend/application/contracts.py` | `7bc0fc4177c81e28868a30a38b864f4213a97c188bb70221d910838b93687228` |
| `src/beeline_backend/application/planner.py` | `cd428060bf5a3d4e1238d197a5da40bbff4a7a6999fe285e7679ef2c3a50e524` |
| `src/beeline_backend/application/ports.py` | `1ae4ee76734a577726327e9e0d066e774ed7123ba57506cc11ba343939c08c3a` |
| `src/beeline_backend/application/services.py` | `198820c71afc2c1294913a590b0055c7925a2a103d16abfe329289744f5f1480` |
| `src/beeline_backend/cli.py` | `11cab83dea0be01303bd50a6eb6db08cdaa134ecc0d09f520956ff2eb49fea7e` |
| `src/beeline_backend/config.py` | `9b8150d21f2260ad38e7a99bf70fac2b7582100664bbf8e2159792e24b39479c` |
| `src/beeline_backend/domain/__init__.py` | `0ecf2bcb7a4c666bf57487256ceb2e41e51bc3e32c84dd76908388653ab2d95f` |
| `src/beeline_backend/domain/errors.py` | `14065c986ef99e1be5aad43512ae1c9a06691af4d80871d9c3a778c8c32e45bb` |
| `src/beeline_backend/domain/model.py` | `0d765e9307c339173fe0395d572a8d9e2ff77adc043bf56c4f6536b5710ba586` |
| `src/beeline_backend/infrastructure/__init__.py` | `318ee4234d87df4091528065efeda8861f84cdeba4a110f6b5d8c48df46c0257` |
| `src/beeline_backend/infrastructure/clock.py` | `de5f7c1d81739d8c788f3f1c8ead972c8556413a462611484670e054fdcb0b23` |
| `src/beeline_backend/infrastructure/db.py` | `e0bd2929c5e0a9b1b0111589cb75a7e785f3ebda264aba6dea11a47607cd991a` |
| `src/beeline_backend/infrastructure/gateway.py` | `1e167b507f30f51a81f9bae1efd162633395758e6933d4eda7c778269be3d2b9` |
| `src/beeline_backend/infrastructure/importer.py` | `184c946c381d93e6bd2af32d69c69fb4af01132d79971608f9b6b60aa38ef66d` |
| `src/beeline_backend/infrastructure/models.py` | `37f9db316e7d9a957f9504b64898927d5f84e857fdb395359aafadff249d276a` |
| `src/beeline_backend/infrastructure/providers.py` | `e031fe4b590fcf8370d79c376e6c52e1f6f48b8ec78c0e9da83e68577fcbd808` |
| `src/beeline_backend/infrastructure/reports.py` | `85d84af8e91647d713fcbb50453ec2940ab917bc4f19fc70dd658715d626b244` |
| `src/beeline_backend/main.py` | `3f282e2de5db40af1737a79033f8afec6e0d27abda341c9bab5a4726698bfe34` |
| `src/beeline_backend/presentation/__init__.py` | `afddb00667a2feb89139f763eec222bfcdc5992cabe75aaed2321e5ac3a469f0` |
| `src/beeline_backend/presentation/api.py` | `d7020ab62a9c6b7d7056cc37ae137240d0f8dcf21369647ceaf209ce8655e3c9` |
| `src/beeline_backend/presentation/dto.py` | `c42854c428f67b2e73e72d80f9cc822a9f8083f254343de8b55074c79d9c6025` |
| `tests/conftest.py` | `9b8c908e20b310d317fc167e6e94f186a471bf9f36c0f6669b58610b2eefc22f` |
| `tests/test_dgis.py` | `798efaeeab8b496ec80a39868b8db225d764163191494c0e23a3f6f8a7b0233f` |
| `tests/test_domain.py` | `8e2345a2c447b29bece946206d858638abf99fc0b7db3404b13108b0ef4e5fe0` |
| `tests/test_frontend_contract.py` | `46dae3b02120fef5d5ea720074a661e60ad309e11bd94812ae6c9d1540a51fe5` |
| `tests/test_http_flow.py` | `db27a5f26ebfe4c63e494749fd106e1da965f419cef727831e56fbe6cd4ab21b` |
| `tests/test_importer.py` | `7a529a98605acd9f768c2a63e91be08bed36f376de95600a13ed8dbe4c1473f6` |
| `tests/test_nominatim.py` | `9010043af176730e47414701a4ec93ab05dbd11e33542cbeb0ade9a129ce3e5f` |
| `tests/test_osrm.py` | `817623ab0286fb801e1ac320073e8b1c8b495cbd9b6e5e88b14aa0492d9935c6` |
| `tests/test_planner_contract.py` | `a5b02701af02d165c6db032656ffab8def043c8ab64459b23be0502adb8a1ec4` |
| `tests/test_reports.py` | `763134f28e223a8cd184275a123d0e9fac0625013c6130f6461840f24fa9121b` |
| `uv.lock` | `9dad40dd17f9429abda39d1e1e9a0ad4a41a1218e7855123474c6e2466f0e40e` |
