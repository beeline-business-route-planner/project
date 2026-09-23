# T01. Persistence жизненного цикла планов

## Цель

Создать целевую модель хранения plan/event/baseline и репозиторные примитивы. HTTP и
бизнес-orchestration в этой задаче не реализуются.

## Исполнитель и зависимости

- Исполнитель: Backend A.
- Зависимость: T00.
- Параллельно: T02, A01/A02.
- Блокирует: G01.

## Объём работ

1. Ввести `ApprovalStatus`: `pending`, `approved`, `rejected`.
2. Привести `PlanKind` к `initial`, `replan`, `event_replan`; убрать старое имя
   `manual_replan` с согласованной миграцией enum.
3. Расширить `Plan` полями из `user-case/BACKEND.md`:
   - `planning_date`;
   - lifecycle status и timestamps;
   - `calculation_cutoff_at`;
   - обязательные счётчики результата;
   - неизменяемые ссылки на upload/base/event.
4. Удалить `Plan.is_baseline` из рабочей модели и миграции целевого состояния.
5. Создать отдельный `BaselineResult`, связанный один-к-одному только с initial.
6. Расширить `ReplanningEvent` рабочей датой, lifecycle и четырьмя типами события,
   включая `engineer_available`.
7. Добавить `Request.status` и состояние доступности инженера, необходимые для проверки
   переходов и позднего approve.
8. Определить версионирование входных данных так, чтобы до approved initial могли
   сосуществовать несколько uploads с одинаковыми внешними номерами заявок. Нельзя
   сохранять глобальный unique, запрещающий согласованный сценарий.
9. Добавить/обновить DTO, репозитории и UoW без бизнес-логики:
   - current approved по `(region, planning_date, approved_at)`;
   - история по региону в обратном порядке;
   - pending siblings;
   - pessimistic lock записи plan для decision;
   - approved events после заданного момента;
   - baseline CRUD.
10. Создать безопасную миграцию без редактирования старых migration-файлов.

## Инварианты БД

- current не хранится отдельным boolean-флагом;
- один рабочий Plan никогда не является baseline;
- event plan обязан иметь `triggered_by_event_id`;
- replan/event replan обязаны иметь `based_on_plan_id`;
- timestamps согласованы со status;
- одна заявка не может одновременно быть stop и unassigned одного plan;
- новая версия upload не уничтожает историческую версию данных.

## Не входит

- approve/reject orchestration;
- автоматическое отклонение siblings;
- HTTP schemas/routes;
- построение diff;
- изменение алгоритма.

## Изоляция от параллельной T02

T01 владеет `core/db/**`, миграциями и persistence DTO. Она не меняет
`api/plans/diff.py` и публичную структуру вычисляемого diff. Если T02 нужны типы снимка,
они согласуются через G01, а не копируются в модели БД.

## Критерии приёмки

1. Чистая и обновляемая БД получают целевую схему.
2. Репозиторий выбирает current только среди approved и только за указанную дату.
3. Несколько pending initial одного региона/дня могут сосуществовать.
4. Baseline невозможно получить через выборку рабочих plans.
5. Event поддерживает все четыре согласованных типа.
6. Есть row-lock primitive для будущего approve/reject.
7. `make check` проходит.
