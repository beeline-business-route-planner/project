# G04. Интеграционный барьер event replan

## Цель

Соединить T07 и A04 и доказать атомарный lifecycle события вместе с планом.

## Входы и исполнитель

- Требует: T07 и A04.
- Исполнитель: Backend A.
- Backend B: ревью API/lifecycle/report visibility.
- Algorithm: ревью event adapter/audit.
- Блокирует: G05.

## Объём работ

1. Подключить pure event contract без ORM/lifecycle внутри алгоритма.
2. Проверить единую транзакцию event + payload + plan.
3. Проверить approve/reject обоих объектов.
4. Проверить, что только approved event меняет фактическое состояние request/engineer и
   попадает в отчёт.
5. Проверить detail/diff срочной заявки без upload.
6. Проверить повторное событие после обратного перехода инженера.
7. Проверить rollback при каждой группе ошибок: validation, routing, algorithm audit, DB.

## Обязательные сценарии

- urgent request approved/rejected;
- cancel active request и запрет повторной отмены;
- unavailable → approve → available → approve → unavailable снова;
- запрет второго pending event;
- алгоритм упал — event отсутствует;
- approve event plan со сменившейся base отклонён;
- approved events видны в report snapshot, остальные отсутствуют.

## Критерии приёмки

1. Event и plan lifecycle не расходятся.
2. Ни одна ошибка не оставляет orphan event/request/plan.
3. Последующие планы основываются только на approved фактах.
4. `make check` проходит.
