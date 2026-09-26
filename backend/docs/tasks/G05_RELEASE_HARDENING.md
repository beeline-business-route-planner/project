# G05. Финальная интеграция и готовность к сдаче

## Цель

Проверить весь согласованный user case как единую систему и устранить только найденные
интеграционные дефекты. Новые продуктовые возможности на этом этапе не добавляются.

## Входы и исполнители

- Требует: G02, G03, G04, T06, T08, T09, A05.
- Backend A владеет lifecycle/planning regression.
- Backend B владеет read/diff/export/report regression.
- Algorithm владеет audit/constraints/metrics regression.
- Завершение требует совместного review всех трёх зон.

## Полная матрица проверки

### Initial

- один/несколько регионов;
- partial success;
- cutoff после начала смены;
- несколько pending до approve;
- approve/reject/sibling rejection;
- запрет Excel после approved initial;
- отдельный baseline.

### Replan

- только от current approved;
- locked history;
- полный snapshot;
- вычисляемый diff;
- поздний безопасный approve и все согласованные conflicts;
- rejected plan никогда не становится base.

### Events

- четыре типа;
- одно pending event;
- event+plan atomicity;
- согласованный status при approve/reject;
- повторный transition после обратного события;
- только approved event влияет на следующие расчёты и отчёт.

### Чтение и конкурентность

- current по region/day/approved_at;
- history по created_at DESC;
- lazy detail;
- два конкурентных decisions;
- стабильные 409/404/422/502 ошибки;
- frontend после decision может одним reread получить актуальные statuses.

### Файлы

- XLSX любого plan/status;
- региональные PDF + summary;
- ZIP N+1;
- presigned URL и cleanup;
- S3 failures без частичного ответа.

### Данные и миграции

- чистая БД;
- upgrade существующей БД;
- отсутствие `is_baseline` и старой публичной семантики current;
- отсутствие orphan rows после ошибок;
- исторические plans остаются читаемыми.

## Нефункциональные проверки

- `make check`;
- структурные логи не содержат содержимое файлов/секреты;
- нет module-level mutable state;
- конфигурация TTL/S3/budgets typed;
- синхронные endpoints укладываются в ожидаемые размеры MVP;
- документация API не расходится с реальными schemas.

## Не входит

Весь `FUTURE_FUNCTIONALITY.md`: force approve, пользовательское время события, несколько
pending events, manual plan editing, actual tracking, event journal, дополнительные
фильтры, async jobs и повторный Excel после approved initial.

## Условие завершения

1. Все обязательные сценарии user case воспроизводимы на чистой БД.
2. Нет известных критических/высоких нарушений lifecycle.
3. Каждый исполнитель подтвердил свою зону.
4. Все найденные ограничения перечислены явно, а не скрыты fallback-поведением.
5. `make check` проходит.
6. Владельцу сообщено, какие защищённые документы `agents-docs/*` устарели; агент их не
   редактирует.
