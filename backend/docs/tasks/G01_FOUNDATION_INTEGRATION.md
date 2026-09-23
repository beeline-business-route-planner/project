# G01. Интеграционный барьер фундамента

## Цель

Слить T01 и T02 в один устойчивый фундамент: ORM-сущности преобразуются в единый полный
snapshot, а diff DTO становится частью будущей карточки плана.

## Входы и исполнитель

- Требует: T01 и T02 в общей ветке.
- Исполнитель: Backend A.
- Backend B: обязательное ревью и проверка diff fixtures.
- Algorithm продолжает свою дорожку и не ждёт G01.
- Блокирует: T03 и T04.

## Объём работ

1. Устранить конфликты DTO без протекания ORM в pure diff.
2. Реализовать единый assembler полного `PlanSnapshot`:
   - все инженеры, включая неиспользованных;
   - assigned stops;
   - unassigned requests;
   - urgent requests без `upload_id`;
   - метрики и lifecycle metadata.
3. Загрузка содержимого плана не должна ограничиваться только `plan.upload_id`, иначе
   event-plan потеряет срочные заявки.
4. Расширить detail DTO полями status, current, planning date, cutoff, timestamps и diff.
5. Для initial assembler возвращает `diff = null`.
6. Для replan/event replan base загружается строго по `based_on_plan_id`, после чего
   вызывается pure diff T02.
7. Сохранить ленивую модель: list содержит summary, detail — полный plan + diff.

## Не входит

- новые HTTP routes;
- approve/reject;
- initial/replan orchestration;
- алгоритм.

## Критерии приёмки

1. Один публичный detail DTO покрывает initial/replan/event replan.
2. Snapshot включает всех инженеров и все заявки плана независимо от источника.
3. Diff никогда не ищет base по времени создания.
4. Старый presenter либо адаптирован, либо заменён без дублирования представлений.
5. `make check` проходит.
6. После merge T03 и T04 могут менять разные API-домены без конфликтов.
